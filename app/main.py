import hmac
import logging
import shutil
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI, File, Form, Header, HTTPException, UploadFile
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from .config import Settings
from .engine import PRESETS, Engine, decode_image
from .store import Store

log = logging.getLogger(__name__)
STATIC = Path(__file__).parent / "static"
IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp"}
VIDEO_EXTENSIONS = {".mp4", ".mov", ".avi"}
ARTIFACTS = {"annotated.jpg", "annotated.mp4", "preview.jpg", "report.json", "detections.csv"}


def create_app(settings=None, engine=None):
    settings = settings or Settings()
    engine = engine or Engine(settings)
    store = Store(settings.data_dir)
    jobs_root = settings.data_dir / "jobs"
    jobs_root.mkdir(exist_ok=True)
    # 清理上次进程被中断时留下的原文件。
    for source in jobs_root.glob("*/source.*"):
        source.unlink(missing_ok=True)
    executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="yolo")
    slots = threading.BoundedSemaphore(8)

    @asynccontextmanager
    async def lifespan(app):
        yield
        executor.shutdown(wait=True)

    app = FastAPI(title="YOLO Vision Studio", version="1.0.0", lifespan=lifespan)
    app.state.store = store
    app.state.settings = settings

    @app.middleware("http")
    async def check_upload_envelope(request, call_next):
        if request.method == "POST" and request.url.path == "/api/jobs":
            provided = request.headers.get("x-api-key", "")
            if settings.api_key and not hmac.compare_digest(provided.encode(), settings.api_key.encode()):
                return JSONResponse({"detail": "访问密钥错误或未填写"}, status_code=401)
            length = request.headers.get("content-length")
            if length is None:
                return JSONResponse({"detail": "上传请求必须提供 Content-Length"}, status_code=411)
            try:
                size = int(length)
            except ValueError:
                return JSONResponse({"detail": "Content-Length 无效"}, status_code=400)
            if size < 0 or size > (settings.max_upload_mb + 1) * 1024 * 1024:
                return JSONResponse({"detail": "上传请求超过大小限制"}, status_code=413)
        return await call_next(request)

    def authorize(x_api_key: str = Header(default="")):
        if settings.api_key and not hmac.compare_digest(x_api_key.encode(), settings.api_key.encode()):
            raise HTTPException(401, "访问密钥错误或未填写")

    def lookup(job_id):
        # 防止用户通过 ID 构造路径。
        try:
            if str(uuid.UUID(job_id)) != job_id:
                raise ValueError
        except ValueError:
            raise HTTPException(404, "任务不存在") from None
        job = store.get(job_id)
        if not job:
            raise HTTPException(404, "任务不存在")
        return job

    def process(job, source, output):
        try:
            store.update(job["id"], status="running", progress=1)
            result = engine.run(job, source, output, lambda value: store.update(job["id"], progress=value))
            store.update(job["id"], status="completed", progress=100, **result)
        except Exception as exc:
            log.exception("Detection job %s failed", job["id"])
            # 未完成的标注文件不保留。
            for artifact in output.iterdir():
                if artifact != source:
                    artifact.unlink(missing_ok=True)
            message = str(exc) if isinstance(exc, ValueError) else "检测失败，请检查服务日志、模型和运行环境"
            store.update(job["id"], status="failed", error=message)
        finally:
            source.unlink(missing_ok=True)
            slots.release()

    @app.get("/api/health")
    def health():
        return {
            "status": "ok",
            "model_ready": Path(settings.model).is_file(),
            "model": Path(settings.model).name,
            "device": settings.device,
            "auth_required": bool(settings.api_key),
            "max_upload_mb": settings.max_upload_mb,
            "max_video_seconds": settings.max_video_seconds,
        }

    @app.post("/api/jobs", status_code=202, dependencies=[Depends(authorize)])
    async def submit(file: UploadFile = File(...), confidence: float = Form(0.35), preset: str = Form("all")):
        if not 0.05 <= confidence <= 0.95 or preset not in PRESETS:
            raise HTTPException(422, "置信度应为 0.05–0.95，场景必须是 all/traffic/people")
        name = Path((file.filename or "upload").replace("\\", "/")).name[:160]
        extension = Path(name).suffix.lower()
        if extension not in IMAGE_EXTENSIONS | VIDEO_EXTENSIONS:
            raise HTTPException(415, "支持 JPG、PNG、WebP、MP4、MOV、AVI")
        if not slots.acquire(blocking=False):
            raise HTTPException(429, "任务队列已满，请稍后再试")
        job_id = str(uuid.uuid4())
        output = jobs_root / job_id
        output.mkdir()
        source = output / ("source" + extension)
        submitted = False
        try:
            size = 0
            with source.open("wb") as stream:
                while chunk := await file.read(1024 * 1024):
                    size += len(chunk)
                    if size > settings.max_upload_mb * 1024 * 1024:
                        raise HTTPException(413, f"文件不能超过 {settings.max_upload_mb} MB")
                    stream.write(chunk)
            if not size:
                raise HTTPException(422, "文件内容为空")
            kind = "image" if extension in IMAGE_EXTENSIONS else "video"
            if kind == "image":
                try:
                    decode_image(source)
                except ValueError as exc:
                    raise HTTPException(422, str(exc)) from exc
            job = store.create(job_id, name, kind, confidence, preset)
            executor.submit(process, job, source, output)
            submitted = True
            return job
        finally:
            await file.close()
            if not submitted:
                shutil.rmtree(output)
                slots.release()

    @app.get("/api/jobs", dependencies=[Depends(authorize)])
    def history():
        return store.list()

    @app.get("/api/jobs/{job_id}", dependencies=[Depends(authorize)])
    def get_job(job_id: str):
        return lookup(job_id)

    @app.get("/api/jobs/{job_id}/files/{filename}", dependencies=[Depends(authorize)])
    def artifact(job_id: str, filename: str):
        job = lookup(job_id)
        if job["status"] != "completed" or filename not in ARTIFACTS:
            raise HTTPException(404, "结果文件不存在")
        path = jobs_root / job_id / filename
        if not path.is_file():
            raise HTTPException(404, "结果文件不存在")
        return FileResponse(path, filename=filename)

    @app.delete("/api/jobs/{job_id}", status_code=204, dependencies=[Depends(authorize)])
    def delete_job(job_id: str):
        job = lookup(job_id)
        if job["status"] in {"queued", "running"}:
            raise HTTPException(409, "任务执行中，完成后可删除")
        shutil.rmtree(jobs_root / job_id, ignore_errors=True)
        store.delete(job_id)

    app.mount("/", StaticFiles(directory=STATIC, html=True), name="studio")
    return app


app = create_app()
