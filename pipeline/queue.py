"""Durable evaluation queue backed by PostgreSQL.

Jobs survive restarts, are claimed with `FOR UPDATE SKIP LOCKED` (so any number
of worker threads or processes can share the queue), are retried on failure and
are re-claimed if a worker dies mid-evaluation (stale heartbeat).
"""

import logging
import threading
import time

from config import settings
from db import Json, connection, execute, fetch_one
from pipeline.evaluation import evaluate_project, initial_pipeline

log = logging.getLogger(__name__)


def enqueue(project_id: str) -> int:
    """Queue a (re-)evaluation. Returns the job id; reuses a pending job if any."""
    with connection() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT id FROM evaluation_jobs WHERE project_id = %s AND status IN ('queued', 'running')",
            (project_id,),
        )
        row = cur.fetchone()
        if row:
            return row[0]
        cur.execute(
            "INSERT INTO evaluation_jobs (project_id) VALUES (%s) RETURNING id", (project_id,)
        )
        job_id = cur.fetchone()[0]
        cur.execute(
            "UPDATE projects SET status = 'queued', pipeline = %s, updated_at = now() WHERE project_id = %s",
            (Json(initial_pipeline()), project_id),
        )
        return job_id


def queue_position(project_id: str) -> int | None:
    row = fetch_one(
        """
        SELECT position FROM (
            SELECT project_id, row_number() OVER (ORDER BY created_at) AS position
            FROM evaluation_jobs WHERE status = 'queued'
        ) q WHERE project_id = %s
        """,
        (project_id,),
    )
    return row["position"] if row else None


def _claim() -> dict | None:
    return fetch_one(
        """
        UPDATE evaluation_jobs SET
            status = 'running', attempts = attempts + 1,
            started_at = now(), heartbeat_at = now()
        WHERE id = (
            SELECT id FROM evaluation_jobs
            WHERE status = 'queued'
               OR (status = 'running' AND heartbeat_at < now() - make_interval(mins => %s))
            ORDER BY created_at
            FOR UPDATE SKIP LOCKED
            LIMIT 1
        )
        RETURNING id, project_id, attempts
        """,
        (settings.job_stale_minutes,),
    )


def _finish(job: dict, error: str | None) -> None:
    if error is None:
        execute("UPDATE evaluation_jobs SET status = 'done', finished_at = now(), last_error = NULL WHERE id = %s", (job["id"],))
        return
    if job["attempts"] < settings.job_max_attempts:
        execute("UPDATE evaluation_jobs SET status = 'queued', last_error = %s WHERE id = %s", (error[:2000], job["id"]))
        log.warning("Job %s failed (attempt %s), re-queued: %s", job["id"], job["attempts"], error)
    else:
        execute("UPDATE evaluation_jobs SET status = 'failed', finished_at = now(), last_error = %s WHERE id = %s", (error[:2000], job["id"]))
        execute(
            "UPDATE projects SET status = 'failed', last_error = %s, updated_at = now() WHERE project_id = %s",
            (error[:2000], job["project_id"]),
        )
        log.error("Job %s failed permanently: %s", job["id"], error)


class Worker:
    """Background threads that drain the evaluation queue."""

    def __init__(self, concurrency: int | None = None, poll_interval: float = 2.0):
        self.concurrency = max(1, concurrency or settings.worker_concurrency)
        self.poll_interval = poll_interval
        self._stop = threading.Event()
        self._threads: list[threading.Thread] = []

    def start(self) -> None:
        for i in range(self.concurrency):
            thread = threading.Thread(target=self._loop, name=f"evalio-worker-{i}", daemon=True)
            thread.start()
            self._threads.append(thread)
        log.info("Evaluation worker started with %d thread(s)", self.concurrency)

    def stop(self, timeout: float = 5.0) -> None:
        self._stop.set()
        for thread in self._threads:
            thread.join(timeout=timeout)

    def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                job = _claim()
            except Exception as exc:
                log.error("Could not poll the job queue: %s", exc)
                self._stop.wait(10)
                continue
            if not job:
                self._stop.wait(self.poll_interval)
                continue
            self.run_job(job)

    @staticmethod
    def run_job(job: dict) -> None:
        log.info("Job %s: evaluating project %s (attempt %s)", job["id"], job["project_id"], job["attempts"])

        def heartbeat() -> None:
            try:
                execute("UPDATE evaluation_jobs SET heartbeat_at = now() WHERE id = %s", (job["id"],))
            except Exception:
                pass

        error = None
        started = time.monotonic()
        try:
            evaluate_project(job["project_id"], heartbeat=heartbeat)
        except LookupError as exc:  # project deleted meanwhile
            error = None
            log.info("Job %s skipped: %s", job["id"], exc)
        except Exception as exc:
            log.exception("Job %s crashed", job["id"])
            error = f"{type(exc).__name__}: {exc}"
        _finish(job, error)
        log.info("Job %s finished in %.1fs", job["id"], time.monotonic() - started)
