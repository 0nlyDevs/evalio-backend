import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException

from db import Json, execute, fetch_all, fetch_one
from pipeline.evaluation import index_for_search, initial_pipeline
from pipeline.queue import enqueue, queue_position
from routes.schemas import ProjectCreate, ReviewIn, SearchIn, serialize_project
from services import llm, vectorstore

router = APIRouter(tags=["Projects"])

_RANKED_SQL = """
    SELECT p.*, r.rank, r.ranked_total FROM projects p
    LEFT JOIN (
        SELECT project_id,
               rank() OVER (PARTITION BY hackathon_id ORDER BY overall_score DESC) AS rank,
               count(*) OVER (PARTITION BY hackathon_id) AS ranked_total
        FROM projects WHERE overall_score IS NOT NULL
    ) r ON r.project_id = p.project_id
"""


def _is_showcase(row: dict) -> bool:
    return bool((row.get("verdict") or {}).get("demo"))


def get_project_row(project_id: str) -> dict:
    row = fetch_one(_RANKED_SQL + " WHERE p.project_id = %s", (project_id,))
    if not row:
        raise HTTPException(status_code=404, detail="Project not found")
    return row


@router.post("/create-project", summary="Submit a project; the jury evaluates it in the background")
def create_project(body: ProjectCreate):
    if body.hackathon_id is not None:
        hackathon = fetch_one("SELECT * FROM hackathons WHERE id = %s", (body.hackathon_id,))
        if not hackathon:
            raise HTTPException(status_code=404, detail="Hackathon not found")
        if not hackathon["is_allowed"]:
            raise HTTPException(status_code=403, detail="Submissions are closed for this hackathon")
        if hackathon.get("deadline") and hackathon["deadline"] < datetime.now(timezone.utc):
            raise HTTPException(status_code=403, detail="The submission deadline has passed")
        duplicate = fetch_one(
            "SELECT project_id FROM projects WHERE hackathon_id = %s AND lower(github_link) = lower(%s)",
            (body.hackathon_id, body.github_link),
        )
        if duplicate:
            raise HTTPException(status_code=409, detail="This repository was already submitted to this hackathon")

    project_id = str(uuid.uuid4())
    row = fetch_one(
        """
        INSERT INTO projects (project_id, hackathon_id, name, short_description, long_description,
                              github_link, demo_link, theme, is_reviewed, project_type, status, pipeline)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, FALSE, %s, 'queued', %s)
        RETURNING *
        """,
        (
            project_id, body.hackathon_id, body.name or body.short_description[:80], body.short_description,
            body.long_description, body.github_link, body.demo_link, body.theme, body.project_type,
            Json(initial_pipeline()),
        ),
    )
    index_for_search(row)
    job_id = enqueue(project_id)
    return {"message": "Project created", "project_id": project_id, "job_id": job_id}


@router.post("/reevaluate/{project_id}", summary="Run the whole jury again on a project")
def reevaluate(project_id: str):
    row = get_project_row(project_id)
    if _is_showcase(row) and not llm.is_configured():
        raise HTTPException(status_code=409, detail="Showcase projects can only be re-judged when an LLM is configured")
    job_id = enqueue(project_id)
    return {"message": "Re-evaluation queued", "project_id": project_id, "job_id": job_id}


@router.get("/get-project/{project_id}", summary="Full project report: verdict, judges, repo snapshot")
def get_project(project_id: str):
    row = get_project_row(project_id)
    project = serialize_project(row, full=True)
    if project["status"] == "queued":
        project["queue_position"] = queue_position(project_id)
    return {"message": "successful", "project": project}


@router.delete("/delete-project/{project_id}", summary="Delete a submission and its indexes")
def delete_project(project_id: str):
    row = fetch_one("SELECT verdict FROM projects WHERE project_id = %s", (project_id,))
    if row and _is_showcase(row):
        raise HTTPException(status_code=403, detail="Showcase projects can't be deleted")
    if execute("DELETE FROM projects WHERE project_id = %s", (project_id,)) == 0:
        raise HTTPException(status_code=404, detail="Project not found")
    vectorstore.delete_project_vectors(project_id)
    return {"message": "Project deleted", "project_id": project_id}


@router.get("/get-hackathon-projects/{hackathon_id}", summary="Projects of a hackathon, newest first")
def get_hackathon_projects(hackathon_id: int):
    rows = fetch_all(_RANKED_SQL + " WHERE p.hackathon_id = %s ORDER BY p.created_at DESC", (hackathon_id,))
    return {"message": "successful", "projects": [serialize_project(r) for r in rows]}


@router.get("/get-all", summary="All projects, newest first")
def get_all_projects():
    rows = fetch_all(_RANKED_SQL + " ORDER BY p.created_at DESC")
    return {"message": "successful", "projects": [serialize_project(r) for r in rows]}


@router.get("/get-project-score/{project_id}", tags=["Scoring"], summary="Final score and explanation")
def get_project_score(project_id: str):
    row = get_project_row(project_id)
    project = serialize_project(row, full=True)
    verdict = project.get("verdict") or {}
    return {
        "message": "successful",
        "project_id": project_id,
        "status": project["status"],
        "overall_score": project["overall_score"],
        "rank": project.get("rank"),
        "score_explanation": project["score_explanation"] or "Score not generated yet",
        "judge_scores": project["judge_scores"],
        "criteria_scores": project["criteria_scores"],
        "headline": verdict.get("headline"),
    }


@router.post("/review", summary="Mark a project as reviewed by a human judge")
def review_project(body: ReviewIn):
    if execute("UPDATE projects SET is_reviewed = %s, updated_at = now() WHERE project_id = %s", (body.is_reviewed, body.project_id)) == 0:
        raise HTTPException(status_code=404, detail="Project not found")
    return {"message": "successful", "project_id": body.project_id, "is_reviewed": body.is_reviewed}


@router.post("/search", tags=["Search"], summary="Semantic search across submissions")
def search_projects(body: SearchIn):
    matches: list[tuple[str, float]] = []
    try:
        matches = vectorstore.search_projects(body.query, k=12, hackathon_id=body.hackathon_id)
    except Exception:
        matches = []

    results = []
    if matches:
        rows = {r["project_id"]: r for r in fetch_all(_RANKED_SQL + " WHERE p.project_id = ANY(%s)", ([m[0] for m in matches],))}
        results = [
            {"project": serialize_project(rows[pid]), "score": round(similarity, 3)}
            for pid, similarity in matches
            if pid in rows and similarity >= 0.15
        ]
    if not results:  # keyword fallback
        like = f"%{body.query}%"
        params: tuple = (like, like, like, like)
        where = "(p.name ILIKE %s OR p.short_description ILIKE %s OR p.long_description ILIKE %s OR p.theme ILIKE %s)"
        if body.hackathon_id:
            where += " AND p.hackathon_id = %s"
            params = (*params, body.hackathon_id)
        rows = fetch_all(_RANKED_SQL + f" WHERE {where} ORDER BY p.created_at DESC LIMIT 12", params)
        results = [{"project": serialize_project(r), "score": None} for r in rows]

    return {"message": "successful", "results": results, "projects": [r["project"] for r in results]}
