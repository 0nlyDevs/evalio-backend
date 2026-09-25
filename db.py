"""PostgreSQL access: a thread-safe connection pool, small query helpers and
idempotent schema migrations."""

import logging
import threading
from contextlib import contextmanager
from typing import Any, Iterator

import psycopg2
from psycopg2.extras import Json, RealDictCursor
from psycopg2.pool import ThreadedConnectionPool

from config import settings

log = logging.getLogger(__name__)

_pool: ThreadedConnectionPool | None = None
_pool_lock = threading.Lock()


def _get_pool() -> ThreadedConnectionPool:
    global _pool
    if _pool is None:
        with _pool_lock:
            if _pool is None:
                _pool = ThreadedConnectionPool(
                    settings.db_pool_min,
                    settings.db_pool_max,
                    host=settings.db_host,
                    port=settings.db_port,
                    dbname=settings.db_name,
                    user=settings.db_user,
                    password=settings.db_password,
                    connect_timeout=10,
                )
    return _pool


@contextmanager
def connection() -> Iterator[Any]:
    """Borrow a pooled connection; commits on success, rolls back on error."""
    pool = _get_pool()
    conn = pool.getconn()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        # Drop broken connections instead of handing them to the next caller
        pool.putconn(conn, close=bool(conn.closed))


def fetch_one(sql: str, params: tuple | dict = ()) -> dict | None:
    with connection() as conn, conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute(sql, params)
        return cur.fetchone()


def fetch_all(sql: str, params: tuple | dict = ()) -> list[dict]:
    with connection() as conn, conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute(sql, params)
        return list(cur.fetchall())


def execute(sql: str, params: tuple | dict = ()) -> int:
    with connection() as conn, conn.cursor() as cur:
        cur.execute(sql, params)
        return cur.rowcount


def ping() -> bool:
    try:
        fetch_one("SELECT 1 AS ok")
        return True
    except Exception:
        return False


def close_pool() -> None:
    global _pool
    if _pool is not None:
        _pool.closeall()
        _pool = None


# Kept for backwards compatibility with older scripts importing it
def get_database_connection():
    return psycopg2.connect(
        host=settings.db_host,
        port=settings.db_port,
        database=settings.db_name,
        user=settings.db_user,
        password=settings.db_password,
    )


PROJECT_TYPES = [
    "VANILLA_JS", "REACT", "NEXT_JS", "VUE", "NUXT", "ANGULAR", "SVELTE", "SVELTEKIT",
    "ASTRO", "REMIX", "TAILWIND", "NODE_EXPRESS", "FASTAPI", "DJANGO", "SPRING_BOOT",
    "GIN", "RAILS", "LARAVEL", "ACTIX", "SWIFT_UI", "KOTLIN_JETPACK", "REACT_NATIVE",
    "EXPO", "FLUTTER", "DOTNET_MAUI", "IONIC", "NATIVESCRIPT", "OTHER",
]

_MIGRATIONS = [
    """
    CREATE TABLE IF NOT EXISTS hackathons (
        id SERIAL PRIMARY KEY,
        name VARCHAR(255) NOT NULL,
        description TEXT DEFAULT '',
        theme TEXT DEFAULT '',
        is_allowed BOOLEAN DEFAULT FALSE,
        criteria TEXT DEFAULT '',
        deadline TIMESTAMPTZ,
        created_at TIMESTAMPTZ DEFAULT now()
    )
    """,
    f"""
    DO $$
    BEGIN
        IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'project_type') THEN
            CREATE TYPE project_type AS ENUM ({", ".join(f"'{t}'" for t in PROJECT_TYPES)});
        END IF;
    END
    $$;
    """,
    """
    CREATE TABLE IF NOT EXISTS projects (
        id SERIAL PRIMARY KEY,
        project_id VARCHAR(255) UNIQUE NOT NULL,
        hackathon_id INTEGER REFERENCES hackathons(id) ON DELETE SET NULL,
        short_description TEXT DEFAULT '',
        long_description TEXT DEFAULT '',
        github_link TEXT DEFAULT '',
        demo_link TEXT DEFAULT NULL,
        theme TEXT DEFAULT '',
        is_reviewed BOOLEAN DEFAULT FALSE,
        code_agent_analysis JSONB DEFAULT NULL,
        market_agent_analysis JSONB DEFAULT NULL,
        overall_score NUMERIC(5,4) DEFAULT NULL,
        score_explanation TEXT DEFAULT '',
        project_type project_type DEFAULT 'OTHER',
        created_at TIMESTAMPTZ DEFAULT now()
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS evaluations (
        id SERIAL PRIMARY KEY,
        project_id VARCHAR(255) REFERENCES projects(project_id) ON DELETE CASCADE,
        criteria_name VARCHAR(255) NOT NULL,
        score DECIMAL(3,2) DEFAULT 0.00,
        remarks TEXT DEFAULT '',
        agent_type VARCHAR(50) DEFAULT 'code',
        created_at TIMESTAMPTZ DEFAULT now()
    )
    """,
    # Columns added over time (safe on existing databases)
    "ALTER TABLE hackathons ADD COLUMN IF NOT EXISTS technologies TEXT DEFAULT ''",
    "ALTER TABLE hackathons ADD COLUMN IF NOT EXISTS criteria_config JSONB DEFAULT NULL",
    "ALTER TABLE hackathons ADD COLUMN IF NOT EXISTS starts_at TIMESTAMPTZ DEFAULT NULL",
    "ALTER TABLE projects ADD COLUMN IF NOT EXISTS overall_score NUMERIC(5,4) DEFAULT NULL",
    "ALTER TABLE projects ADD COLUMN IF NOT EXISTS score_explanation TEXT DEFAULT ''",
    "ALTER TABLE projects ADD COLUMN IF NOT EXISTS demo_link TEXT DEFAULT NULL",
    "ALTER TABLE projects ADD COLUMN IF NOT EXISTS project_type project_type DEFAULT 'OTHER'",
    "ALTER TABLE projects ADD COLUMN IF NOT EXISTS name TEXT DEFAULT ''",
    "ALTER TABLE projects ADD COLUMN IF NOT EXISTS status VARCHAR(20) DEFAULT 'queued'",
    "ALTER TABLE projects ADD COLUMN IF NOT EXISTS pipeline JSONB DEFAULT '{}'::jsonb",
    "ALTER TABLE projects ADD COLUMN IF NOT EXISTS repo_snapshot JSONB DEFAULT NULL",
    "ALTER TABLE projects ADD COLUMN IF NOT EXISTS product_agent_analysis JSONB DEFAULT NULL",
    "ALTER TABLE projects ADD COLUMN IF NOT EXISTS criteria_scores JSONB DEFAULT '[]'::jsonb",
    "ALTER TABLE projects ADD COLUMN IF NOT EXISTS verdict JSONB DEFAULT NULL",
    "ALTER TABLE projects ADD COLUMN IF NOT EXISTS flags JSONB DEFAULT '[]'::jsonb",
    "ALTER TABLE projects ADD COLUMN IF NOT EXISTS last_error TEXT DEFAULT NULL",
    "ALTER TABLE projects ADD COLUMN IF NOT EXISTS evaluated_at TIMESTAMPTZ DEFAULT NULL",
    "ALTER TABLE projects ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ DEFAULT now()",
    # Widen the score column so rankings keep 4 decimals (was DECIMAL(3,2))
    """
    DO $$
    BEGIN
        IF EXISTS (
            SELECT 1 FROM information_schema.columns
            WHERE table_name = 'projects' AND column_name = 'overall_score'
              AND numeric_scale IS DISTINCT FROM 4
        ) THEN
            ALTER TABLE projects ALTER COLUMN overall_score TYPE NUMERIC(5,4);
        END IF;
    END
    $$;
    """,
    # Legacy rows stored analyses as '[]' – treat them as "not analysed yet"
    "ALTER TABLE projects ALTER COLUMN code_agent_analysis SET DEFAULT NULL",
    "ALTER TABLE projects ALTER COLUMN market_agent_analysis SET DEFAULT NULL",
    # Persistent evaluation queue consumed by the worker(s)
    """
    CREATE TABLE IF NOT EXISTS evaluation_jobs (
        id SERIAL PRIMARY KEY,
        project_id VARCHAR(255) NOT NULL REFERENCES projects(project_id) ON DELETE CASCADE,
        status VARCHAR(20) NOT NULL DEFAULT 'queued',
        attempts INTEGER NOT NULL DEFAULT 0,
        last_error TEXT DEFAULT NULL,
        created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        started_at TIMESTAMPTZ DEFAULT NULL,
        heartbeat_at TIMESTAMPTZ DEFAULT NULL,
        finished_at TIMESTAMPTZ DEFAULT NULL
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_projects_hackathon_id ON projects(hackathon_id)",
    "CREATE INDEX IF NOT EXISTS idx_projects_score ON projects(hackathon_id, overall_score DESC)",
    "CREATE INDEX IF NOT EXISTS idx_evaluations_project_id ON evaluations(project_id)",
    "CREATE INDEX IF NOT EXISTS idx_jobs_status ON evaluation_jobs(status, created_at)",
]

# Timestamps used to be stored without a time zone, which made the frontend
# shift deadlines by the viewer's UTC offset. Values were written as UTC.
_TIMESTAMPTZ_COLUMNS = [
    ("hackathons", "deadline"),
    ("hackathons", "created_at"),
    ("projects", "created_at"),
    ("evaluations", "created_at"),
]


def init_db() -> None:
    with connection() as conn, conn.cursor() as cur:
        # Serialise concurrent boots (API + separate worker processes)
        cur.execute("SELECT pg_advisory_xact_lock(424242)")
        for statement in _MIGRATIONS:
            cur.execute(statement)
        for table, column in _TIMESTAMPTZ_COLUMNS:
            cur.execute(
                """
                SELECT data_type FROM information_schema.columns
                WHERE table_name = %s AND column_name = %s
                """,
                (table, column),
            )
            row = cur.fetchone()
            if row and row[0] == "timestamp without time zone":
                cur.execute(
                    f"ALTER TABLE {table} ALTER COLUMN {column} TYPE TIMESTAMPTZ "
                    f"USING {column} AT TIME ZONE 'UTC'"
                )
        cur.execute(
            "UPDATE projects SET code_agent_analysis = NULL WHERE code_agent_analysis = '[]'::jsonb"
        )
        cur.execute(
            "UPDATE projects SET market_agent_analysis = NULL WHERE market_agent_analysis = '[]'::jsonb"
        )
        # Projects evaluated by the pre-queue version have no job: mark them so
        # the UI offers a re-run instead of showing them as stuck in the queue.
        cur.execute(
            """
            UPDATE projects SET status = 'legacy'
            WHERE status = 'queued' AND (pipeline IS NULL OR pipeline = '{}'::jsonb)
              AND NOT EXISTS (SELECT 1 FROM evaluation_jobs j WHERE j.project_id = projects.project_id)
            """
        )
    log.info("Database schema is up to date")


__all__ = [
    "Json",
    "PROJECT_TYPES",
    "connection",
    "execute",
    "fetch_all",
    "fetch_one",
    "init_db",
    "ping",
    "close_pool",
]
