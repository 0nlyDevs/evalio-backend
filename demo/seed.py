"""Seeds a showcase hackathon with fully evaluated example projects, plus an
open sandbox, so every Evalio deployment has something to explore.

Idempotent: runs on every startup, recreates anything missing (for example a
deleted demo project) and never touches user data. Disable with SEED_DEMO=false.

Scores are not hand-picked: the engineering scorecard, the judges' headline
scores, the weighted final score and the integrity flags are computed by the
jury's own code from the stored repository snapshots.
"""

import json
import logging
import os
import threading
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

from agents.base import now_iso
from agents.code_agent import engineering_scorecard
from agents.head_judge import compute_flags
from db import Json, connection, execute, fetch_all, fetch_one
from demo.showcase import PROJECTS, SANDBOX, SHOWCASE
from pipeline.evaluation import index_for_search, save_verdict
from services import vectorstore
from services.criteria import criteria_names, normalize_criteria, weighted_score

log = logging.getLogger(__name__)

DATA_DIR = Path(__file__).parent / "data"
MODEL_LABEL = "evalio-showcase"


def enabled() -> bool:
    return os.getenv("SEED_DEMO", "true").strip().lower() not in {"0", "false", "no", "off"}


def demo_project_id(repo: str) -> str:
    """Stable ids so showcase links survive redeploys and re-seeding."""
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"evalio-showcase:{repo.lower()}"))


def _ensure_schema() -> None:
    execute("ALTER TABLE hackathons ADD COLUMN IF NOT EXISTS is_demo BOOLEAN DEFAULT FALSE")


def _ensure_hackathon(spec: dict, *, is_allowed: bool, with_dates: bool) -> dict:
    row = fetch_one("SELECT * FROM hackathons WHERE is_demo AND name = %s", (spec["name"],))
    if row:
        return row
    criteria = normalize_criteria(spec["criteria"])
    return fetch_one(
        """
        INSERT INTO hackathons (name, description, theme, technologies, is_allowed, criteria,
                                criteria_config, starts_at, deadline, is_demo)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, TRUE)
        RETURNING *
        """,
        (
            spec["name"], spec["description"], spec["theme"], spec["technologies"], is_allowed,
            criteria_names(criteria), Json(criteria),
            spec.get("starts_at") if with_dates else None,
            spec.get("deadline") if with_dates else None,
        ),
    )


def _load_data(key: str) -> dict:
    with open(DATA_DIR / f"{key}.json", encoding="utf-8") as fh:
        return json.load(fh)


def _criteria_results(spec: dict, criteria: list[dict], judge: str, evidence: list[dict]) -> list[dict]:
    out = []
    for c in criteria:
        if c["judge"] != judge:
            continue
        score, rationale = spec["criteria"][c["name"]]
        out.append({
            "name": c["name"], "weight": c["weight"], "judge": judge, "description": c.get("description", ""),
            "score": score, "rationale": rationale, "strengths": [], "weaknesses": [],
            "evidence": evidence[:2] if judge == "code" else [], "status": "scored",
        })
    return out


def build_reports(spec: dict, hackathon: dict, data: dict) -> tuple[dict, dict, dict, dict]:
    """Assemble the three judge reports and the head judge verdict."""
    criteria = normalize_criteria(hackathon["criteria_config"])
    snapshot = data["snapshot"]
    code, market, product = spec["code"], spec["market"], spec["product"]

    scorecard = engineering_scorecard(snapshot)
    code_report = {
        "agent": "code", "model": MODEL_LABEL, "generated_at": now_iso(), "status": "done",
        "score": round(0.75 * code["review_score"] + 0.25 * scorecard["score"], 2),
        "summary": code["summary"], "architecture": code["architecture"],
        "strengths": code["strengths"], "weaknesses": code["weaknesses"], "risks": code["risks"],
        "evidence": code["evidence"], "scorecard": scorecard,
        "stack": snapshot["stack"], "languages": snapshot["languages"],
        "files_reviewed": code["files_reviewed"],
        "criteria": _criteria_results(spec, criteria, "code", code["evidence"]),
        "error": None,
    }

    scores = market["scores"]
    market_report = {
        "agent": "market", "model": MODEL_LABEL, "generated_at": now_iso(), "status": "done",
        "score": round(scores["market_potential"] * 0.4 + scores["differentiation"] * 0.3 + scores["viability"] * 0.3, 2),
        "summary": market["summary"], "profile": market["profile"], "audience": market["audience"],
        "problem_severity": market["problem_severity"], "market_size": market["market_size"],
        "market_trend": market["market_trend"],
        "competitors": [
            {**c, "url": next((s["url"] for s in data["sources"] if s["id"] == c.get("source")), None)}
            for c in market["competitors"]
        ],
        "differentiation": market["differentiation"], "business": market["business"], "scores": scores,
        "queries": data["queries"], "sources": data["sources"],
        "criteria": _criteria_results(spec, criteria, "market", []),
        "error": None,
    }

    claims = product["claims"]
    verified = sum(1 for c in claims if c["status"] == "implemented") + 0.5 * sum(1 for c in claims if c["status"] == "partial")
    completeness = round(10 * verified / len(claims), 1) if claims else None
    p_scores = {**product["scores"], "completeness": completeness}
    parts = [v for v in p_scores.values() if v is not None]
    product_report = {
        "agent": "product", "model": MODEL_LABEL, "generated_at": now_iso(), "status": "done",
        "score": round(sum(parts) / len(parts), 2),
        "summary": product["summary"], "scores": p_scores, "rationales": product["rationales"],
        "wow_factor": product["wow_factor"], "suggestions": product["suggestions"],
        "claims": claims, "demo": data.get("demo"), "similar_submissions": [],
        "criteria": _criteria_results(spec, criteria, "product", []),
        "error": None,
    }

    results = {"code": code_report, "market": market_report, "product": product_report}
    all_criteria = sorted(
        [c for r in results.values() for c in r["criteria"]],
        key=lambda c: [x["name"] for x in criteria].index(c["name"]),
    )
    project_stub = {"project_type": spec["project_type"]}
    verdict = {
        "agent": "head", "model": MODEL_LABEL, "generated_at": now_iso(), "status": "done",
        "score": weighted_score(all_criteria),
        "judge_scores": {j: results[j]["score"] for j in results},
        "criteria": all_criteria,
        "flags": compute_flags(project_stub, hackathon, snapshot, results),
        "headline": spec["verdict"]["headline"], "summary": spec["verdict"]["summary"],
        "strengths": spec["verdict"]["strengths"], "improvements": spec["verdict"]["improvements"],
        "demo": True, "error": None,
    }
    return code_report, market_report, product_report, verdict


def _insert_project(spec: dict, hackathon: dict, index: int) -> str:
    data = _load_data(spec["key"])
    project_id = demo_project_id(spec["repo"])
    code_report, market_report, product_report, verdict = build_reports(spec, hackathon, data)

    # Stagger submission times inside the event window so lists look natural
    deadline = hackathon.get("deadline") or datetime.now(timezone.utc)
    created = deadline - timedelta(hours=6 * (len(PROJECTS) - index))
    stamp = now_iso()
    pipeline = {s: {"status": "done", "started_at": stamp, "finished_at": stamp} for s in ("ingest", "code", "market", "product", "verdict")}
    pipeline["ingest"]["message"] = f"{data['snapshot']['files']['analyzed']} files analyzed"

    snapshot = {**data["snapshot"]}
    with connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO projects (project_id, hackathon_id, name, short_description, long_description, github_link,
                                  demo_link, theme, is_reviewed, project_type, status, pipeline, repo_snapshot,
                                  code_agent_analysis, market_agent_analysis, product_agent_analysis, created_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, FALSE, %s, 'completed', %s, %s, %s, %s, %s, %s)
            ON CONFLICT (project_id) DO NOTHING
            """,
            (
                project_id, hackathon["id"], spec["name"], spec["short"], spec["long"], spec["repo"],
                spec["demo_link"], hackathon["theme"], spec["project_type"], Json(pipeline), Json(snapshot),
                Json(code_report), Json(market_report), Json(product_report), created,
            ),
        )
    results = {"code": code_report, "market": market_report, "product": product_report}
    save_verdict(project_id, verdict, results, None)
    return project_id


def _index_code_in_background(project_ids: list[tuple[str, str]]) -> None:
    """Index demo repositories so 'Ask the jury' can cite real code. Best effort."""
    from services.repo_ingest import ingest_repository

    def run():
        for project_id, repo in project_ids:
            collection = vectorstore.get_code_collection(project_id)
            if collection is not None and collection.count() > 0:
                continue
            try:
                ingest_repository(repo, project_id=project_id, index=True)
                log.info("Indexed showcase repository %s", repo)
            except Exception as exc:
                log.info("Could not index showcase repository %s: %s", repo, exc)

    threading.Thread(target=run, name="evalio-showcase-index", daemon=True).start()


def seed_demo() -> None:
    if not enabled():
        return
    try:
        _ensure_schema()
        showcase = _ensure_hackathon(SHOWCASE, is_allowed=False, with_dates=True)
        _ensure_hackathon(SANDBOX, is_allowed=True, with_dates=False)

        existing = {r["project_id"] for r in fetch_all("SELECT project_id FROM projects WHERE hackathon_id = %s", (showcase["id"],))}
        created = []
        for index, spec in enumerate(PROJECTS):
            project_id = demo_project_id(spec["repo"])
            if project_id not in existing:
                _insert_project(spec, showcase, index)
                created.append(spec["name"])
            row = fetch_one("SELECT * FROM projects WHERE project_id = %s", (project_id,))
            if row:
                index_for_search(row, spec["market"]["profile"]["pitch"])
        if created:
            log.info("Seeded showcase projects: %s", ", ".join(created))
        _index_code_in_background([(demo_project_id(p["repo"]), p["repo"]) for p in PROJECTS])
    except Exception:
        log.exception("Showcase seeding failed (the API keeps running)")
