"""Real CPU inference on the official bus sample + a generated short video."""

import json
import tempfile
import time
import urllib.request
from pathlib import Path

import cv2
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app


def main():
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        sample = root / "bus.jpg"
        urllib.request.urlretrieve(
            "https://raw.githubusercontent.com/ultralytics/ultralytics/main/ultralytics/assets/bus.jpg",
            sample,
        )
        image = cv2.imread(str(sample))
        video = root / "sample.mp4"
        height, width = image.shape[:2]
        writer = cv2.VideoWriter(str(video), cv2.VideoWriter_fourcc(*"mp4v"), 5, (width, height))
        for _ in range(5):
            writer.write(image)
        writer.release()
        with TestClient(create_app(Settings(data_dir=root / "results"))) as client:
            for source in [sample, video]:
                with source.open("rb") as stream:
                    response = client.post(
                        "/api/jobs",
                        files={"file": (source.name, stream)},
                        data={"preset": "traffic", "confidence": "0.35"},
                    )
                assert response.status_code == 202, response.text
                job_id = response.json()["id"]
                for _ in range(600):
                    job = client.get(f"/api/jobs/{job_id}").json()
                    if job["status"] in {"completed", "failed"}:
                        break
                    time.sleep(0.1)
                assert job["status"] == "completed", job
                assert job["counts"].get("bus", 0) >= 1, job
                assert job["counts"].get("person", 0) >= 1, job
                for filename in [job["artifact"], "report.json", "detections.csv"]:
                    artifact = client.get(f"/api/jobs/{job_id}/files/{filename}")
                    assert artifact.status_code == 200 and artifact.content
                if source == video:
                    capture = cv2.VideoCapture(str(root / "results" / "jobs" / job_id / job["artifact"]))
                    ok, _ = capture.read()
                    capture.release()
                    assert ok, "encoded output is not readable"
                print(json.dumps({key: job[key] for key in ["kind", "counts", "elapsed_seconds"]}))


if __name__ == "__main__":
    main()
