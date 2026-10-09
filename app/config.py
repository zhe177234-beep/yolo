import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Settings:
    model: str = os.getenv("YOLO_MODEL", "models/yolo11n.pt")
    device: str = os.getenv("YOLO_DEVICE", "cpu")
    data_dir: Path = Path(os.getenv("YOLO_DATA_DIR", "data"))
    max_upload_mb: int = int(os.getenv("YOLO_MAX_UPLOAD_MB", "100"))
    max_video_seconds: int = int(os.getenv("YOLO_MAX_VIDEO_SECONDS", "60"))
    api_key: str = os.getenv("YOLO_API_KEY", "")
