"""Shared building blocks for the judge agents."""

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Annotated

from pydantic import BaseModel, Field

from config import settings
from services import llm
from services.llm import Score, StrList, Text, objects_from

log = logging.getLogger(__name__)


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class JudgeContext:
    project: dict
    hackathon: dict | None
    criteria: list[dict]  # criteria routed to this judge
    snapshot: dict | None = None  # repository snapshot (None when ingestion failed)
    extra: dict = field(default_factory=dict)  # outputs of agents that ran earlier

    @property
    def project_name(self) -> str:
        return self.project.get("name") or self.project.get("short_description") or "Untitled project"

    @property
    def description(self) -> str:
        parts = [
            f"Name: {self.project_name}",
            f"Tagline: {self.project.get('short_description') or ''}",
            f"Description: {self.project.get('long_description') or 'n/a'}",
        ]
        if self.project.get("project_type") and self.project["project_type"] != "OTHER":
            parts.append(f"Declared project type: {self.project['project_type']}")
        if self.project.get("demo_link"):
            parts.append(f"Demo: {self.project['demo_link']}")
        return "\n".join(parts)

    @property
    def hackathon_brief(self) -> str:
        h = self.hackathon or {}
        if not h:
            return "Independent submission (no hackathon)."
        lines = [f"Hackathon: {h.get('name', '')}"]
        if h.get("description"):
            lines.append(f"Brief: {h['description'][:800]}")
        if h.get("theme"):
            lines.append(f"Themes: {h['theme']}")
        if h.get("technologies"):
            lines.append(f"Expected technologies: {h['technologies']}")
        return "\n".join(lines)


class Evidence(BaseModel):
    file: Text = ""
    note: Text = ""


class CriterionAssessment(BaseModel):
    score: Score
    rationale: Text
    strengths: StrList = Field(default_factory=list)
    weaknesses: StrList = Field(default_factory=list)
    evidence: Annotated[list[Evidence], objects_from("note")] = Field(default_factory=list)

    @staticmethod
    def example() -> dict:
        return {
            "score": 6.5,
            "rationale": "2-4 sentences explaining the score with concrete observations.",
            "strengths": ["specific strength"],
            "weaknesses": ["specific weakness"],
            "evidence": [{"file": "path/or/source", "note": "what it shows"}],
        }


RUBRIC = """Scoring rubric (0-10, use decimals, be discriminating — most hackathon projects land between 4 and 8):
0-2 missing or broken · 3-4 weak, major gaps · 5-6 works but ordinary · 7-8 strong, clear strengths · 9-10 exceptional, top of the event.
Never give the same score to everything. Base every claim on the evidence provided; if evidence is missing say so and score conservatively."""


def score_criterion(
    persona: str,
    criterion: dict,
    ctx: JudgeContext,
    evidence: str,
) -> dict:
    """Score one hackathon criterion. Returns a criterion result dict (never raises)."""
    base = {
        "name": criterion["name"],
        "weight": criterion["weight"],
        "judge": criterion["judge"],
        "description": criterion.get("description", ""),
    }
    system = f"{persona}\n\n{RUBRIC}"
    user = (
        f"{ctx.hackathon_brief}\n\nPROJECT\n{ctx.description}\n\n"
        f"CRITERION TO SCORE: {criterion['name']}"
        + (f" — {criterion['description']}" if criterion.get("description") else "")
        + f"\n\nEVIDENCE\n{evidence[:11000]}\n\n"
        f"Score the project on '{criterion['name']}' only."
    )
    try:
        result = llm.chat_json(system, user, CriterionAssessment, temperature=0.1)
        return {
            **base,
            "score": result.score,
            "rationale": result.rationale,
            "strengths": result.strengths[:4],
            "weaknesses": result.weaknesses[:4],
            "evidence": [e.model_dump() for e in result.evidence[:5] if e.file or e.note],
            "status": "scored",
        }
    except Exception as exc:
        log.warning("Criterion %r could not be scored: %s", criterion["name"], exc)
        return {**base, "score": None, "rationale": f"Not scored: {exc}", "strengths": [], "weaknesses": [], "evidence": [], "status": "failed"}


def agent_result(agent: str, **payload) -> dict:
    return {
        "agent": agent,
        "model": settings.llm_model,
        "generated_at": now_iso(),
        **payload,
    }


def mean(values: list[float | None]) -> float | None:
    scored = [v for v in values if v is not None]
    return round(sum(scored) / len(scored), 2) if scored else None
