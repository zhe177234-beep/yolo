import io
import threading
import time

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from app.config import Settings
from app.main import create_app


class FakeEngine:
    def run(self, job, source, output, progress):
        progress(50)
        (output / "annotated.jpg").write_bytes(b"test artifact")
        return dict(
            counts={"person": 2},
            total=2,
            width=32,
            height=32,
            artifact="annotated.jpg",
            elapsed_seconds=0.1,
            count_mode="image",
        )


def picture():
    stream = io.BytesIO()
    Image.new("RGB", (32, 32), "white").save(stream, "PNG")
    return stream.getvalue()


@pytest.fixture
def client(tmp_path):
    with TestClient(
        create_app(Settings(data_dir=tmp_path, api_key="secret", max_upload_mb=1), FakeEngine())
    ) as c:
        yield c


def submit(client, content=None, filename="test.png", **params):
    return client.post(
        "/api/jobs",
        headers={"X-API-Key": "secret"},
        files={"file": (filename, content if content is not None else picture())},
        data=params,
    )


def wait_job(client, job_id):
    for _ in range(100):
        job = client.get(f"/api/jobs/{job_id}", headers={"X-API-Key": "secret"}).json()
        if job["status"] in {"completed", "failed"}:
            return job
        time.sleep(0.01)
    pytest.fail("worker did not finish")


def test_image_lifecycle_and_artifact_access(client):
    response = submit(client, filename="../../photo.png")
    assert response.status_code == 202
    job = wait_job(client, response.json()["id"])
    assert job["name"] == "photo.png"
    assert job["total"] == 2 and job["status"] == "completed"
    url = f"/api/jobs/{job['id']}"
    assert client.get(url + "/files/annotated.jpg").status_code == 401
    assert (
        client.get(url + "/files/annotated.jpg", headers={"X-API-Key": "secret"}).content == b"test artifact"
    )
    assert not list(client.app.state.settings.data_dir.glob("jobs/*/source.*"))
    assert client.delete(url, headers={"X-API-Key": "secret"}).status_code == 204
    assert client.get(url, headers={"X-API-Key": "secret"}).status_code == 404


@pytest.mark.parametrize("params", [{"confidence": "nan"}, {"confidence": "1"}, {"preset": "invalid"}])
def test_invalid_settings(client, params):
    assert submit(client, **params).status_code == 422


@pytest.mark.parametrize(
    "content,filename,code",
    [
        (b"", "empty.png", 422),
        (b"bad image", "fake.png", 422),
        (b"abc", "script.exe", 415),
        (b"x" * (1024 * 1024 + 1), "large.png", 413),
    ],
    ids=["empty", "invalid-image", "unsupported", "oversize"],
)
def test_invalid_uploads(client, content, filename, code):
    assert submit(client, content=content, filename=filename).status_code == code
    assert not list(client.app.state.settings.data_dir.glob("jobs/*"))


def test_auth_and_invalid_id(client):
    assert client.get("/api/health").status_code == 200
    assert client.get("/").status_code == 200
    assert client.get("/api/jobs").status_code == 401
    assert client.get("/api/jobs/bad-id", headers={"X-API-Key": "secret"}).status_code == 404


def test_failed_job_releases_slot(tmp_path):
    class BrokenEngine:
        def run(self, *args):
            raise ValueError("模型文件不存在")

    with TestClient(create_app(Settings(data_dir=tmp_path), BrokenEngine())) as c:
        for _ in range(9):
            result = submit(c)
            assert result.status_code == 202
            job = wait_job(c, result.json()["id"])
            assert job["status"] == "failed" and job["error"] == "模型文件不存在"
        assert not list(tmp_path.glob("jobs/*/source.*"))


def test_active_job_cannot_be_deleted(tmp_path):
    released = threading.Event()

    class SlowEngine(FakeEngine):
        def run(self, *args):
            released.wait(timeout=5)
            return super().run(*args)

    with TestClient(create_app(Settings(data_dir=tmp_path), SlowEngine())) as c:
        job = submit(c).json()
        try:
            assert c.delete(f"/api/jobs/{job['id']}").status_code == 409
        finally:
            released.set()


def test_restart_marks_interrupted_jobs(tmp_path):
    from app.store import Store

    store = Store(tmp_path)
    store.create("old", "old.png", "image", 0.35, "all")
    assert Store(tmp_path).get("old")["status"] == "failed"


def test_upload_envelope_is_checked_before_parsing(client):
    assert client.post("/api/jobs", content=b"invalid multipart").status_code == 401
    response = client.post(
        "/api/jobs",
        content=b"too big",
        headers={"X-API-Key": "secret", "Content-Length": str(3 * 1024 * 1024)},
    )
    assert response.status_code == 413
