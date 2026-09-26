"""Request models (camelCase, as sent by the frontend) and response serializers."""

from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

from db import PROJECT_TYPES
from services.criteria import hackathon_criteria
from services.repo_ingest import IngestError, parse_repo_url


class _Model(BaseModel):
    model_config = ConfigDict(populate_by_name=True, str_strip_whitespace=True)


class CriterionIn(_Model):
    name: str = Field(min_length=1, max_length=80)
    weight: float = Field(default=1, ge=0, le=100)
    judge: str | None = None
    description: str | None = Field(default=None, max_length=300)


class HackathonCreate(_Model):
    name: str = Field(min_length=3, max_length=120)
    description: str = Field(default="", max_length=4000)
    theme: str = Field(default="", max_length=1000)
    technologies: str = Field(default="", max_length=1000)
    criteria: str | list[CriterionIn] | None = None
    starts_at: datetime | None = Field(default=None, alias="startsAt")
    deadline: datetime | None = None
    is_allowed: bool = Field(default=True, alias="isAllowed")


class HackathonUpdate(_Model):
    name: str | None = Field(default=None, min_length=3, max_length=120)
    description: str | None = Field(default=None, max_length=4000)
    theme: str | None = Field(default=None, max_length=1000)
    technologies: str | None = Field(default=None, max_length=1000)
    criteria: str | list[CriterionIn] | None = None
    starts_at: datetime | None = Field(default=None, alias="startsAt")
    deadline: datetime | None = None
    is_allowed: bool | None = Field(default=None, alias="isAllowed")


class ProjectCreate(_Model):
    name: str = Field(default="", max_length=80)
    short_description: str = Field(alias="shortDescription", min_length=5, max_length=160)
    long_description: str = Field(default="", alias="longDescription", max_length=6000)
    github_link: str = Field(alias="githubLink", max_length=300)
    demo_link: str | None = Field(default=None, alias="demoLink", max_length=300)
    theme: str = Field(default="", max_length=300)
    hackathon_id: int | None = Field(default=None, alias="hackathonId")
    project_type: str = Field(default="OTHER", alias="projectType")

    @field_validator("github_link")
    @classmethod
    def _valid_repo(cls, value: str) -> str:
        try:
            return parse_repo_url(value).url
        except IngestError as exc:
            raise ValueError(str(exc)) from exc

    @field_validator("demo_link")
    @classmethod
    def _valid_demo(cls, value: str | None) -> str | None:
        if not value:
            return None
        if not value.lower().startswith(("http://", "https://")):
            value = "https://" + value
        return value

    @field_validator("project_type")
    @classmethod
    def _valid_type(cls, value: str) -> str:
        value = (value or "OTHER").upper()
        if value not in PROJECT_TYPES:
            raise ValueError(f"projectType must be one of {', '.join(PROJECT_TYPES)}")
        return value

    @field_validator("hackathon_id", mode="before")
    @classmethod
    def _hackathon_id(cls, value: Any) -> Any:
        return None if value in ("", None) else value


class ReviewIn(_Model):
    project_id: str
    is_reviewed: bool = Field(alias="isReviewed")


class ChatTurn(_Model):
    input: str = ""
    output: str = ""


class ChatIn(_Model):
    question: str = Field(min_length=1, max_length=2000)
    project_id: str | None = None
    chathistory: list[ChatTurn] = Field(default_factory=list)


class SearchIn(_Model):
    query: str = Field(min_length=1, max_length=300)
    hackathon_id: int | None = Field(default=None, alias="hackathonId")


# ---------------------------------------------------------------------------
# Serializers
# ---------------------------------------------------------------------------


def _iso(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.isoformat()
    return str(value)


def _score10(value: Any) -> float | None:
    """overall_score is stored on a 0..1 scale; the API speaks 0..10."""
    return None if value is None else round(float(value) * 10, 2)


def hackathon_phase(row: dict) -> str:
    now = datetime.now(timezone.utc)
    starts_at, deadline = row.get("starts_at"), row.get("deadline")
    if deadline and deadline < now:
        return "judging"
    if not row.get("is_allowed"):
        return "closed"
    if starts_at and starts_at > now:
        return "upcoming"
    return "open"


def serialize_hackathon(row: dict, stats: dict | None = None) -> dict:
    criteria = hackathon_criteria(row)
    return {
        "_id": str(row["id"]),
        "id": row["id"],
        "name": row["name"],
        "description": row.get("description") or "",
        "theme": row.get("theme") or "",
        "technologies": row.get("technologies") or "",
        "criteria": ", ".join(c["name"] for c in criteria),
        "criteria_config": criteria,
        "is_allowed": bool(row.get("is_allowed")),
        "isAllowed": bool(row.get("is_allowed")),
        "phase": hackathon_phase(row),
        "is_demo": bool(row.get("is_demo")),
        "starts_at": _iso(row.get("starts_at")),
        "deadline": _iso(row.get("deadline")),
        "created_at": _iso(row.get("created_at")),
        "stats": stats or {},
    }


_SNAPSHOT_PRIVATE = {"readme", "manifests"}


def serialize_project(row: dict, full: bool = False) -> dict:
    verdict = row.get("verdict") or {}
    flags = row.get("flags") or []
    data = {
        "_id": str(row["id"]),
        "project_id": row["project_id"],
        "hackathon_id": row.get("hackathon_id"),
        "name": row.get("name") or row.get("short_description") or "Untitled",
        "short_description": row.get("short_description") or "",
        "long_description": row.get("long_description") or "",
        "github_link": row.get("github_link") or "",
        "demo_link": row.get("demo_link"),
        "theme": row.get("theme") or "",
        "project_type": row.get("project_type") or "OTHER",
        "is_reviewed": bool(row.get("is_reviewed")),
        "status": row.get("status") or "queued",
        "pipeline": row.get("pipeline") or {},
        "overall_score": _score10(row.get("overall_score")),
        "judge_scores": verdict.get("judge_scores") or {},
        "headline": verdict.get("headline") or "",
        "flags": flags,
        "criteria_scores": [
            {k: c.get(k) for k in ("name", "score", "weight", "judge", "status")}
            for c in (row.get("criteria_scores") or [])
        ],
        "last_error": row.get("last_error"),
        "created_at": _iso(row.get("created_at")),
        "evaluated_at": _iso(row.get("evaluated_at")),
    }
    if "rank" in row:
        data["rank"] = row["rank"]
        data["ranked_total"] = row.get("ranked_total")
    if full:
        snapshot = row.get("repo_snapshot")
        if snapshot:
            snapshot = {k: v for k, v in snapshot.items() if k not in _SNAPSHOT_PRIVATE}
            if "history" in snapshot:
                snapshot["history"] = {k: v for k, v in snapshot["history"].items() if k != "commit_dates"}
        data.update(
            verdict=verdict or None,
            criteria_scores=row.get("criteria_scores") or [],
            code_agent_analysis=row.get("code_agent_analysis"),
            market_agent_analysis=row.get("market_agent_analysis"),
            product_agent_analysis=row.get("product_agent_analysis"),
            repo_snapshot=snapshot,
            score_explanation=row.get("score_explanation") or "",
        )
    return data
