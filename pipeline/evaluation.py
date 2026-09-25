"""Runs the full jury for one project:

    ingest repo ─┬─> Code Judge ──┐
                 └─> Market Judge ┴─> Product Judge ─> Head Judge ─> save + rank

Every stage writes its status into `projects.pipeline` so the UI can show live
progress, and a failing stage degrades the evaluation instead of aborting it.
"""

import json
import logging
from concurrent.futures import ThreadPoolExecutor
from typing import Callable

from agents import code_agent, head_judge, market_agent, product_agent
from agents.base import JudgeContext, now_iso
from db import Json, connection, execute, fetch_one
from services import vectorstore
from services.criteria import hackathon_criteria
from services.repo_ingest import ingest_repository

log = logging.getLogger(__name__)

STAGES = ("ingest", "code", "market", "product", "verdict")


def initial_pipeline() -> dict:
    return {stage: {"status": "pending"} for stage in STAGES}


def _set_stage(project_id: str, stage: str, status: str, message: str | None = None) -> None:
    patch = {"status": status}
    if status == "running":
        patch["started_at"] = now_iso()
    elif status in {"done", "failed", "partial", "skipped"}:
        patch["finished_at"] = now_iso()
    if message:
        patch["message"] = message[:300]
    execute(
        """
        UPDATE projects
        SET pipeline = jsonb_set(
                COALESCE(pipeline, '{}'::jsonb), %s,
                COALESCE(pipeline -> %s, '{}'::jsonb) || %s::jsonb),
            updated_at = now()
        WHERE project_id = %s
        """,
        ([stage], stage, json.dumps(patch), project_id),
    )


def _stage(project_id: str, stage: str, fn: Callable[[], dict | None], heartbeat: Callable[[], None]) -> dict | None:
    heartbeat()
    _set_stage(project_id, stage, "running")
    try:
        result = fn()
    except Exception as exc:
        log.exception("Stage %s failed for %s", stage, project_id)
        _set_stage(project_id, stage, "failed", str(exc))
        return None
    status = (result or {}).get("status", "done")
    _set_stage(project_id, stage, "done" if status == "done" else status, (result or {}).get("error"))
    return result


def _load(project_id: str) -> tuple[dict, dict | None]:
    project = fetch_one("SELECT * FROM projects WHERE project_id = %s", (project_id,))
    if not project:
        raise LookupError(f"Project {project_id} not found")
    hackathon = None
    if project.get("hackathon_id"):
        hackathon = fetch_one("SELECT * FROM hackathons WHERE id = %s", (project["hackathon_id"],))
    return project, hackathon


def index_for_search(project: dict, extra: str = "") -> None:
    text = "\n".join(filter(None, [
        project.get("name"), project.get("short_description"), project.get("long_description"),
        project.get("theme"), extra,
    ]))
    vectorstore.upsert_project_document(project["project_id"], text, project.get("hackathon_id"))


def evaluate_project(project_id: str, heartbeat: Callable[[], None] = lambda: None) -> None:
    project, hackathon = _load(project_id)
    criteria = hackathon_criteria(hackathon)
    log.info("Evaluating %s (%s) with %d criteria", project_id, project.get("name"), len(criteria))

    execute(
        "UPDATE projects SET status = 'running', pipeline = %s, last_error = NULL, updated_at = now() WHERE project_id = %s",
        (Json(initial_pipeline()), project_id),
    )
    index_for_search(project)

    # 1. Ingest + index the repository
    snapshot = None
    ingest_error = None
    heartbeat()
    _set_stage(project_id, "ingest", "running")
    try:
        snapshot = ingest_repository(project["github_link"], project_id=project_id)
        execute("UPDATE projects SET repo_snapshot = %s WHERE project_id = %s", (Json(snapshot), project_id))
        _set_stage(project_id, "ingest", "done",
                   f"{snapshot['files']['analyzed']} files, {snapshot['indexed_chunks']} chunks indexed")
    except Exception as exc:  # IngestError or unexpected clone failures
        ingest_error = str(exc)
        log.warning("Ingestion failed for %s: %s", project_id, exc)
        _set_stage(project_id, "ingest", "failed", ingest_error)

    def ctx_for(judge: str, **extra) -> JudgeContext:
        return JudgeContext(
            project=project, hackathon=hackathon, snapshot=snapshot,
            criteria=[c for c in criteria if c["judge"] == judge], extra=extra,
        )

    # 2. Code + Market judges in parallel
    with ThreadPoolExecutor(max_workers=2, thread_name_prefix="judge") as pool:
        code_future = pool.submit(_stage, project_id, "code", lambda: code_agent.run(ctx_for("code", ingest_error=ingest_error)), heartbeat)
        market_future = pool.submit(_stage, project_id, "market", lambda: market_agent.run(ctx_for("market")), heartbeat)
        code_result = code_future.result()
        market_result = market_future.result()

    execute(
        "UPDATE projects SET code_agent_analysis = %s, market_agent_analysis = %s WHERE project_id = %s",
        (Json(code_result) if code_result else None, Json(market_result) if market_result else None, project_id),
    )

    # 3. Product judge (uses market competitors + code index)
    product_result = _stage(
        project_id, "product",
        lambda: product_agent.run(ctx_for("product", market=market_result or {})),
        heartbeat,
    )
    execute(
        "UPDATE projects SET product_agent_analysis = %s WHERE project_id = %s",
        (Json(product_result) if product_result else None, project_id),
    )

    # 4. Head judge: weighted score, flags, verdict
    results = {"code": code_result, "market": market_result, "product": product_result}
    verdict = _stage(
        project_id, "verdict",
        lambda: head_judge.run(JudgeContext(project=project, hackathon=hackathon, criteria=criteria, snapshot=snapshot), results),
        heartbeat,
    )
    save_verdict(project_id, verdict, results, ingest_error)

    if market_result and market_result.get("profile"):
        index_for_search(project, f"{market_result['profile'].get('pitch', '')} {market_result['profile'].get('category', '')}")
    log.info("Evaluation finished for %s: %s", project_id, (verdict or {}).get("score"))


def save_verdict(project_id: str, verdict: dict | None, results: dict, ingest_error: str | None) -> None:
    score = (verdict or {}).get("score")
    stage_ok = [bool(r) and r.get("status") == "done" for r in results.values()]
    if score is None:
        status = "failed"
    elif all(stage_ok) and not ingest_error:
        status = "completed"
    else:
        status = "partial"

    explanation = ""
    if verdict:
        bullets = [f"- {s}" for s in verdict.get("strengths", [])] + [f"- To improve: {s}" for s in verdict.get("improvements", [])]
        explanation = "\n".join([verdict.get("headline", ""), *bullets]).strip()

    with connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
            UPDATE projects SET
                verdict = %s, criteria_scores = %s, flags = %s,
                overall_score = %s, score_explanation = %s,
                status = %s, last_error = %s, evaluated_at = now(), updated_at = now()
            WHERE project_id = %s
            """,
            (
                Json(verdict) if verdict else None,
                Json((verdict or {}).get("criteria", [])),
                Json((verdict or {}).get("flags", [])),
                round(score / 10, 4) if score is not None else None,
                explanation,
                status,
                ingest_error,
                project_id,
            ),
        )
        # Per-criterion rows for reporting/analytics
        cur.execute("DELETE FROM evaluations WHERE project_id = %s", (project_id,))
        for item in (verdict or {}).get("criteria", []):
            if item.get("score") is None:
                continue
            cur.execute(
                "INSERT INTO evaluations (project_id, criteria_name, score, remarks, agent_type) VALUES (%s, %s, %s, %s, %s)",
                (project_id, item["name"][:255], round(item["score"] / 10, 2), item.get("rationale", ""), item["judge"]),
            )
