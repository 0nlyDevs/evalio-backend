"""Code Judge — the technical member of the panel.

Works from the ingested repository: deterministic engineering signals (tests,
CI, docs, tooling, secrets, commit hygiene) plus retrieval over the indexed
source code, then scores every criterion routed to it with file-level evidence.
"""

import json
import logging
from typing import Annotated

from pydantic import BaseModel, Field

from agents.base import (
    RUBRIC,
    Evidence,
    JudgeContext,
    agent_result,
    score_criterion,
)
from services import llm, vectorstore
from services.llm import Score, StrList, Text, objects_from

log = logging.getLogger(__name__)

PERSONA = (
    "You are the Code Judge on a hackathon jury: a staff software engineer who reads the "
    "actual source code. You reward working, well-structured, secure code and you are not "
    "impressed by dependency lists or boilerplate. Cite file paths for every observation."
)

REVIEW_QUERIES = [
    "main application entry point, server setup, routing and core business logic",
    "error handling, input validation and exception management",
    "authentication, authorization, secrets and API keys handling",
    "database access, data models and external API integration",
    "core feature implementation and algorithms",
]

CRITERION_QUERIES = {
    "test": ["unit tests, integration tests, assertions and test fixtures"],
    "secur": ["authentication, authorization, password hashing, tokens, input sanitization, SQL queries"],
    "scal": ["caching, queues, async processing, database queries and pagination"],
    "perform": ["performance optimisation, caching, memoization, database indexes, async"],
    "doc": ["README setup instructions, docstrings, comments and API documentation"],
    "architect": ["project structure, modules, layers, services, dependency injection"],
    "ui": ["UI components, layout, styling, responsive design and accessibility"],
    "ai": ["LLM prompts, model calls, embeddings, machine learning pipeline"],
}


class TechnicalReview(BaseModel):
    summary: Text
    architecture: Text = ""
    strengths: StrList = Field(default_factory=list)
    weaknesses: StrList = Field(default_factory=list)
    risks: StrList = Field(default_factory=list)
    evidence: Annotated[list[Evidence], objects_from("note")] = Field(default_factory=list)
    score: Score

    @staticmethod
    def example() -> dict:
        return {
            "summary": "3-4 sentence technical assessment of what the code actually does and how well.",
            "architecture": "1-2 sentences on structure and main components.",
            "strengths": ["concrete strength with file reference"],
            "weaknesses": ["concrete weakness with file reference"],
            "risks": ["security or reliability risk"],
            "evidence": [{"file": "src/app.py", "note": "what this file shows"}],
            "score": 6.5,
        }


def engineering_scorecard(snapshot: dict) -> dict:
    """Deterministic 0-10 subscores from repository signals (no LLM)."""
    s = snapshot["signals"]
    files = snapshot["files"]
    history = snapshot["history"]
    code_files = max(1, files["code_files"])

    testing = 0.0
    if s["has_tests"]:
        ratio = s["test_files"] / code_files
        testing = min(10.0, 4 + ratio * 40)
    if s["has_ci"]:
        testing = min(10.0, testing + 1.5)

    documentation = 0.0
    if s["has_readme"]:
        documentation = min(10.0, 2 + s["readme_chars"] / 600 + s["readme_sections"] * 0.5)

    tooling_points = [s["has_linter"], s["has_type_checking"], s["has_ci"], s["has_docker"], s["has_env_example"], s["has_gitignore"]]
    tooling = round(10 * sum(tooling_points) / len(tooling_points), 1)

    hygiene = 10.0
    if s.get("hardcoded_secrets"):
        hygiene -= 5
    if s.get("committed_secrets_risk"):
        hygiene -= 3
    if s.get("committed_dependencies"):
        hygiene -= 2
    commits = history.get("commit_count", 0)
    if commits <= 2:
        hygiene -= 2
    elif commits and history.get("low_quality_messages", 0) / commits > 0.5:
        hygiene -= 1.5

    subscores = {
        "testing": round(testing, 1),
        "documentation": round(documentation, 1),
        "tooling": tooling,
        "hygiene": round(max(0.0, hygiene), 1),
    }
    return {"subscores": subscores, "score": round(sum(subscores.values()) / len(subscores), 1)}


def repo_facts(snapshot: dict) -> str:
    history = snapshot["history"]
    facts = {
        "repository": snapshot["repo"]["url"],
        "files": snapshot["files"],
        "languages": [f"{lang['name']} {round(lang['share'] * 100)}%" for lang in snapshot["languages"][:6]],
        "frameworks": [f["label"] for f in snapshot["stack"]["frameworks"]],
        "notable_libraries": snapshot["stack"]["libraries"],
        "signals": {k: v for k, v in snapshot["signals"].items() if k not in {"hardcoded_secrets"}},
        "hardcoded_secret_findings": snapshot["signals"].get("hardcoded_secrets", []),
        "commits": history.get("commit_count"),
        "contributors": len(history.get("contributors", [])),
        "first_commit": history.get("first_commit_at"),
        "last_commit": history.get("last_commit_at"),
        "largest_files": snapshot["largest_files"][:5],
    }
    return json.dumps(facts, indent=1, default=str) + "\n\nDirectory tree:\n" + snapshot["tree"][:2500]


def _criterion_queries(name: str) -> list[str]:
    lowered = name.lower()
    queries = [f"code related to {name}"]
    for key, extra in CRITERION_QUERIES.items():
        if key in lowered:
            queries.extend(extra)
    return queries + REVIEW_QUERIES[:2]


def run(ctx: JudgeContext) -> dict:
    project_id = ctx.project["project_id"]
    snapshot = ctx.snapshot

    if not snapshot:
        error = ctx.extra.get("ingest_error") or "Repository could not be ingested."
        # A missing/private repo is the team's responsibility: no code, no points.
        # Infrastructure failures (timeouts...) stay unscored so weights redistribute.
        missing = "not found" in error.lower() or "private" in error.lower()
        criteria = [
            {**c, "score": 0.0 if missing else None, "status": "no_code" if missing else "failed",
             "rationale": error, "strengths": [], "weaknesses": [], "evidence": []}
            for c in ctx.criteria
        ]
        return agent_result(
            "code", status="failed", summary=f"The repository could not be analysed: {error}",
            criteria=criteria, score=0.0 if missing else None, error=error,
        )

    scorecard = engineering_scorecard(snapshot)
    facts = repo_facts(snapshot)

    review_chunks = vectorstore.query_code(project_id, REVIEW_QUERIES, k=4, max_chars=10000, code_only=True)
    review_context = vectorstore.format_chunks(review_chunks)

    review: TechnicalReview | None = None
    review_error = None
    try:
        review = llm.chat_json(
            f"{PERSONA}\n\n{RUBRIC}",
            (
                f"{ctx.hackathon_brief}\n\nPROJECT\n{ctx.description}\n\n"
                f"REPOSITORY FACTS (measured, trustworthy)\n{facts}\n\n"
                f"Automated engineering scorecard: {json.dumps(scorecard)}\n\n"
                f"SOURCE CODE EXCERPTS\n{review_context}\n\n"
                "Write the overall technical review of this codebase."
            ),
            TechnicalReview,
            temperature=0.1,
        )
    except Exception as exc:
        review_error = str(exc)
        log.warning("Code review failed for %s: %s", project_id, exc)

    criteria_results = []
    for criterion in ctx.criteria:
        chunks = vectorstore.query_code(
            project_id, _criterion_queries(criterion["name"]), k=4, max_chars=7000,
            code_only="doc" not in criterion["name"].lower(),
        )
        evidence = (
            f"REPOSITORY FACTS\n{facts}\n\nENGINEERING SCORECARD\n{json.dumps(scorecard)}\n\n"
            f"RELEVANT SOURCE CODE\n{vectorstore.format_chunks(chunks)}"
        )
        result = score_criterion(PERSONA, criterion, ctx, evidence)
        if result["score"] is None:
            # LLM unavailable: fall back to the measured scorecard so the project still ranks
            result.update(score=scorecard["score"], status="heuristic",
                          rationale="Scored from measured repository signals (LLM unavailable).")
        criteria_results.append(result)

    # The LLM review dominates; measured signals keep it honest
    headline = round(0.75 * review.score + 0.25 * scorecard["score"], 2) if review else scorecard["score"]

    return agent_result(
        "code",
        status="done" if review else "partial",
        score=headline,
        summary=review.summary if review else "Automated signals only — the LLM review could not be generated.",
        architecture=review.architecture if review else "",
        strengths=review.strengths[:5] if review else [],
        weaknesses=review.weaknesses[:5] if review else [],
        risks=review.risks[:5] if review else [],
        evidence=[e.model_dump() for e in review.evidence[:6]] if review else [],
        scorecard=scorecard,
        stack=snapshot["stack"],
        languages=snapshot["languages"],
        files_reviewed=sorted({c["path"] for c in review_chunks})[:20],
        criteria=criteria_results,
        error=review_error,
    )
