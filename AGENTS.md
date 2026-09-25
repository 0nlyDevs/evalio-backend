# AGENTS.md

## Running

```bash
python server.py          # API on http://0.0.0.0:8000 (+ in-process evaluation worker)
python worker.py          # optional extra worker process (set RUN_WORKER=false on the API)
docker compose up --build # API + 2 workers + PostgreSQL + Chroma
```

Swagger UI at `/docs`. `git` must be installed (repos are cloned). Copy `.env.example` to `.env`.

## Architecture

- `POST /api/create-project` validates the submission, stores it and inserts a row in
  `evaluation_jobs`. It never runs analysis in the request.
- `pipeline/queue.py` workers claim jobs with `FOR UPDATE SKIP LOCKED`, retry failures
  (`JOB_MAX_ATTEMPTS`) and re-claim jobs whose heartbeat is older than `JOB_STALE_MINUTES`.
- `pipeline/evaluation.py` runs: ingest → (Code Judge ∥ Market Judge) → Product Judge → Head Judge.
  Each stage updates `projects.pipeline[stage]` (`pending|running|done|partial|failed`).
- `services/repo_ingest.py` clones with `git clone --depth`, keeps tracked text files (skips
  vendored/binary/lock/minified), computes the snapshot (files, languages, stack, signals, git
  history, secret scan) and indexes line-numbered chunks in Chroma collection `code-<project_id>`.
  Chunks carry `kind: code|doc`; implementation reviews query with `code_only=True`.
- Criteria: `services/criteria.py` normalises hackathon criteria to `[{name, weight, judge}]` and
  routes each to `code|market|product` by keywords. Final score = weighted mean of scored criteria
  (`weighted_score`), stored as `overall_score` on a 0..1 scale; the API always returns 0..10.
- LLM calls go through `services/llm.py` (`chat_json` with a pydantic schema that defines an
  `example()`), never directly through the OpenAI client.

## Conventions

- Agents never raise for LLM problems: they return `status: partial|failed` and the pipeline
  degrades gracefully. Missing/private repo → code criteria score 0; infra failure → unscored.
- DB access via `db.fetch_one / fetch_all / execute / connection()` (pooled). Use `Json(...)` for JSONB.
- Schema changes go in `db._MIGRATIONS` as idempotent statements (`ADD COLUMN IF NOT EXISTS`)
  and in `SQL_SCHEMA.sql`.
- Request bodies are pydantic models in `routes/schemas.py` (camelCase aliases for the frontend).
  Validation errors return `{"detail": "<readable message>", "errors": [...]}`.
- All user-facing text is in English.

## Project statuses

`queued` → `running` → `completed` (all judges done) | `partial` (some stage failed) | `failed`.
`legacy` marks projects evaluated before the job queue existed; re-evaluate them.
