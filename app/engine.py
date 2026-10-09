import csv
import json
import math
import subprocess
import time
from collections import Counter
from pathlib import Path

from .config import Settings

PRESETS = {"all": None, "traffic": [0, 1, 2, 3, 5, 7], "people": [0]}


def decode_image(path):
    from PIL import Image, ImageOps, UnidentifiedImageError

    Image.MAX_IMAGE_PIXELS = 20_000_000
    try:
        with Image.open(path) as original:
            if original.width * original.height > Image.MAX_IMAGE_PIXELS:
                raise ValueError("图片不能超过 2000 万像素")
            image = ImageOps.exif_transpose(original).convert("RGB")
            image.thumbnail((1600, 1600))
            return image.copy()
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError) as exc:
        raise ValueError("无法读取图片，请上传有效的 JPG、PNG 或 WebP") from exc


class Engine:
    def __init__(self, settings: Settings):
        self.settings = settings
        self._model = None

    def model(self):
        if self._model is None:
            from ultralytics import YOLO

            if not Path(self.settings.model).is_file():
                raise ValueError("模型文件不存在，请先运行 python scripts/setup_model.py")
            self._model = YOLO(self.settings.model)
            if self._model.task != "detect":
                raise ValueError("工作台仅支持目标检测模型，请使用 detect 权重")
        return self._model

    def predict(self, source, confidence, preset):
        import cv2

        model = self.model()
        classes = PRESETS[preset]
        if preset != "all" and model.names.get(0) != "person":
            raise ValueError("自定义模型请使用“全部类别”模式；场景筛选适用于 COCO 模型")
        result = model.predict(
            source=source,
            conf=confidence,
            classes=classes,
            device=self.settings.device,
            imgsz=640,
            verbose=False,
        )[0]
        detections = []
        for box in result.boxes:
            class_id = int(box.cls.item())
            detections.append(
                {
                    "class_id": class_id,
                    "label": result.names[class_id],
                    "confidence": round(float(box.conf.item()), 4),
                    "box": [round(float(x), 1) for x in box.xyxy[0].tolist()],
                }
            )
        # Ultralytics 返回 BGR 标注图。
        return cv2.cvtColor(result.plot(), cv2.COLOR_BGR2RGB), detections

    def image(self, source, output, confidence, preset, progress):
        from PIL import Image

        image = decode_image(source)
        annotated, detections = self.predict(image, confidence, preset)
        Image.fromarray(annotated).save(output / "annotated.jpg", quality=92)
        progress(95)
        counts = dict(Counter(d["label"] for d in detections))
        return dict(
            counts=counts,
            total=len(detections),
            detections=detections,
            width=image.width,
            height=image.height,
            artifact="annotated.jpg",
            count_mode="image",
        )

    def video(self, source, output, confidence, preset, progress):
        import cv2
        import imageio_ffmpeg

        cap = cv2.VideoCapture(str(source))
        writer = None
        raw = output / "silent.mp4"
        rows, peak, index = [], Counter(), 0
        try:
            if not cap.isOpened():
                raise ValueError("无法解码视频，请使用 MP4、MOV 或 AVI")
            fps = cap.get(cv2.CAP_PROP_FPS)
            frames = cap.get(cv2.CAP_PROP_FRAME_COUNT)
            if not math.isfinite(fps) or not 1 <= fps <= 120:
                raise ValueError("视频帧率无效，支持 1–120 FPS")
            if frames > fps * self.settings.max_video_seconds:
                raise ValueError(f"视频最长支持 {self.settings.max_video_seconds} 秒")
            while True:
                ok, frame = cap.read()
                if not ok:
                    break
                if index >= fps * self.settings.max_video_seconds:
                    raise ValueError(f"视频最长支持 {self.settings.max_video_seconds} 秒")
                height, width = frame.shape[:2]
                scale = min(1, 1280 / max(width, height))
                width, height = max(2, int(width * scale) // 2 * 2), max(2, int(height * scale) // 2 * 2)
                frame = cv2.resize(frame, (width, height))
                annotated, detections = self.predict(frame, confidence, preset)
                if writer is None:
                    writer = cv2.VideoWriter(str(raw), cv2.VideoWriter_fourcc(*"mp4v"), fps, (width, height))
                    if not writer.isOpened():
                        raise ValueError("视频编码器不可用")
                writer.write(cv2.cvtColor(annotated, cv2.COLOR_RGB2BGR))
                counts = Counter(d["label"] for d in detections)
                for label, count in counts.items():
                    peak[label] = max(peak[label], count)
                for detection in detections:
                    rows.append(dict(frame=index, seconds=round(index / fps, 3), **detection))
                if index == 0:
                    cv2.imwrite(str(output / "preview.jpg"), cv2.cvtColor(annotated, cv2.COLOR_RGB2BGR))
                index += 1
                if index % 10 == 0:
                    progress(min(90, round(index / max(frames, index + 1) * 90)))
        finally:
            cap.release()
            if writer is not None:
                writer.release()
        if index == 0:
            raise ValueError("视频中没有可读取的画面")
        progress(92)
        subprocess.run(
            [
                imageio_ffmpeg.get_ffmpeg_exe(),
                "-y",
                "-i",
                str(raw),
                "-an",
                "-c:v",
                "libx264",
                "-pix_fmt",
                "yuv420p",
                "-movflags",
                "+faststart",
                str(output / "annotated.mp4"),
            ],
            check=True,
            capture_output=True,
            timeout=180,
        )
        raw.unlink(missing_ok=True)
        return dict(
            counts=dict(peak),
            total=sum(peak.values()),
            detections=rows,
            frames=index,
            duration=round(index / fps, 2),
            width=width,
            height=height,
            artifact="annotated.mp4",
            count_mode="peak_per_class",
        )

    def run(self, job, source, output, progress):
        started = time.perf_counter()
        result = getattr(self, job["kind"])(source, output, job["confidence"], job["preset"], progress)
        result["elapsed_seconds"] = round(time.perf_counter() - started, 2)
        report = {**job, **result, "model": Path(self.settings.model).name, "status": "completed"}
        (output / "report.json").write_text(
            json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        with (output / "detections.csv").open("w", encoding="utf-8-sig", newline="") as stream:
            fields = ["frame", "seconds", "class_id", "label", "confidence", "x1", "y1", "x2", "y2"]
            writer = csv.DictWriter(stream, fieldnames=fields)
            writer.writeheader()
            for detection in result.pop("detections"):
                row = {k: v for k, v in detection.items() if k != "box"}
                row.update(zip(["x1", "y1", "x2", "y2"], detection["box"]))
                writer.writerow(row)
        return result
