from fastapi import APIRouter, HTTPException

from db import Json, fetch_all, fetch_one
from routes.schemas import (
    HackathonCreate,
    HackathonUpdate,
    serialize_hackathon,
    serialize_project,
)
from services.criteria import criteria_names, normalize_criteria

router = APIRouter(tags=["Hackathons"])

_STATS_SQL = """
    SELECT hackathon_id,
           count(*) AS projects,
           count(*) FILTER (WHERE status IN ('completed', 'partial')) AS evaluated,
           count(*) FILTER (WHERE status IN ('queued', 'running')) AS in_progress,
           max(overall_score) AS top_score,
           avg(overall_score) AS avg_score
    FROM projects
    {where}
    GROUP BY hackathon_id
"""


def _stats(row: dict | None) -> dict:
    row = row or {}
    top, avg = row.get("top_score"), row.get("avg_score")
    return {
        "projects": row.get("projects", 0),
        "evaluated": row.get("evaluated", 0),
        "in_progress": row.get("in_progress", 0),
        "top_score": round(float(top) * 10, 2) if top is not None else None,
        "avg_score": round(float(avg) * 10, 2) if avg is not None else None,
    }


def get_hackathon_row(hackathon_id: int) -> dict:
    row = fetch_one("SELECT * FROM hackathons WHERE id = %s", (hackathon_id,))
    if not row:
        raise HTTPException(status_code=404, detail="Hackathon not found")
    return row


@router.post("/create-hackathon", summary="Create a hackathon with weighted judging criteria")
def create_hackathon(body: HackathonCreate):
    if body.starts_at and body.deadline and body.deadline <= body.starts_at:
        raise HTTPException(status_code=422, detail="The deadline must be after the start date")
    criteria = normalize_criteria(body.model_dump()["criteria"])
    row = fetch_one(
        """
        INSERT INTO hackathons (name, description, theme, technologies, is_allowed, criteria, criteria_config, starts_at, deadline)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
        RETURNING id
        """,
        (
            body.name, body.description, body.theme, body.technologies, body.is_allowed,
            criteria_names(criteria), Json(criteria), body.starts_at, body.deadline,
        ),
    )
    return {"message": "Hackathon created", "hackathon_id": row["id"]}


@router.patch("/update-hackathon/{hackathon_id}", summary="Update a hackathon (e.g. open/close submissions)")
def update_hackathon(hackathon_id: int, body: HackathonUpdate):
    get_hackathon_row(hackathon_id)
    fields = body.model_dump(exclude_unset=True)
    if "criteria" in fields:
        criteria = normalize_criteria(fields.pop("criteria"))
        fields["criteria"] = criteria_names(criteria)
        fields["criteria_config"] = Json(criteria)
    if not fields:
        raise HTTPException(status_code=422, detail="Nothing to update")
    assignments = ", ".join(f"{column} = %s" for column in fields)
    fetch_one(
        f"UPDATE hackathons SET {assignments} WHERE id = %s RETURNING id",
        (*fields.values(), hackathon_id),
    )
    return get_hackathon(hackathon_id)


@router.get("/get-hackathon/{hackathon_id}", summary="Hackathon details with submission stats")
def get_hackathon(hackathon_id: int):
    row = get_hackathon_row(hackathon_id)
    stats = fetch_one(_STATS_SQL.format(where="WHERE hackathon_id = %s"), (hackathon_id,))
    return {"message": "successful", "hackathon": serialize_hackathon(row, _stats(stats))}


@router.get("/get-all-hackathons", summary="List hackathons, newest first")
def get_all_hackathons():
    rows = fetch_all("SELECT * FROM hackathons ORDER BY created_at DESC")
    stats = {r["hackathon_id"]: r for r in fetch_all(_STATS_SQL.format(where="WHERE hackathon_id IS NOT NULL"))}
    return {
        "message": "successful",
        "hackathons": [serialize_hackathon(r, _stats(stats.get(r["id"]))) for r in rows],
    }


@router.get("/get-hackathon-leaderboard/{hackathon_id}", tags=["Scoring"], summary="Ranked projects of a hackathon")
def get_hackathon_leaderboard(hackathon_id: int):
    hackathon = get_hackathon_row(hackathon_id)
    rows = fetch_all(
        """
        SELECT p.*,
               CASE WHEN p.overall_score IS NULL THEN NULL
                    ELSE rank() OVER (PARTITION BY p.overall_score IS NULL ORDER BY p.overall_score DESC) END AS rank,
               count(p.overall_score) OVER () AS ranked_total
        FROM projects p
        WHERE p.hackathon_id = %s
        ORDER BY p.overall_score DESC NULLS LAST, p.created_at ASC
        """,
        (hackathon_id,),
    )
    leaderboard = []
    for row in rows:
        project = serialize_project(row)
        project["score"] = project["overall_score"]
        leaderboard.append(project)
    return {
        "message": "successful",
        "hackathon": serialize_hackathon(hackathon),
        "hackathon_name": hackathon["name"],
        "leaderboard": leaderboard,
    }
