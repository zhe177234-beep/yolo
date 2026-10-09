import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path


class Store:
    def __init__(self, root: Path):
        root.mkdir(parents=True, exist_ok=True)
        self.db = root / "jobs.sqlite3"
        with self.connect() as conn:
            conn.execute("CREATE TABLE IF NOT EXISTS jobs (id TEXT PRIMARY KEY, payload TEXT NOT NULL)")
        # 单进程执行器重启后不能继续旧的任务；保留明确的失败记录。
        for job in self.list(100000):
            if job["status"] in {"queued", "running"}:
                self.update(job["id"], status="failed", error="服务已重启，请重新提交文件")

    def connect(self):
        return sqlite3.connect(self.db, timeout=30)

    def create(self, job_id, name, kind, confidence, preset):
        job = dict(
            id=job_id,
            name=name,
            kind=kind,
            confidence=confidence,
            preset=preset,
            status="queued",
            progress=0,
            created_at=datetime.now(timezone.utc).isoformat(),
        )
        with self.connect() as conn:
            conn.execute("INSERT INTO jobs VALUES (?, ?)", (job_id, json.dumps(job, ensure_ascii=False)))
        return job

    def get(self, job_id):
        with self.connect() as conn:
            row = conn.execute("SELECT payload FROM jobs WHERE id=?", (job_id,)).fetchone()
        return json.loads(row[0]) if row else None

    def update(self, job_id, **changes):
        job = self.get(job_id)
        job.update(changes)
        with self.connect() as conn:
            conn.execute(
                "UPDATE jobs SET payload=? WHERE id=?", (json.dumps(job, ensure_ascii=False), job_id)
            )
        return job

    def list(self, limit=50):
        with self.connect() as conn:
            rows = conn.execute("SELECT payload FROM jobs ORDER BY rowid DESC LIMIT ?", (limit,)).fetchall()
        return [json.loads(row[0]) for row in rows]

    def delete(self, job_id):
        with self.connect() as conn:
            conn.execute("DELETE FROM jobs WHERE id=?", (job_id,))
