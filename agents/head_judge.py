"""Head Judge — aggregates the panel.

The final score is a deterministic weighted mean of the per-criterion scores
given by the three judges (using the hackathon's weights), so rankings are
reproducible and explainable. The LLM only writes the verdict text.
Integrity/rule flags are computed from hard evidence, like a real jury would.
"""

import logging
from datetime import datetime

from pydantic import BaseModel, Field

from agents.base import JudgeContext, agent_result
from services import llm
from services.criteria import JUDGE_LABELS, weighted_score
from services.llm import StrList, Text

log = logging.getLogger(__name__)


class Verdict(BaseModel):
    headline: Text
    summary: Text
    strengths: StrList = Field(default_factory=list)
    improvements: StrList = Field(default_factory=list)

    @staticmethod
    def example() -> dict:
        return {
            "headline": "One punchy sentence a jury would say about this project.",
            "summary": "3-4 sentences combining the technical, market and product views.",
            "strengths": ["top strength"],
            "improvements": ["most important improvement"],
        }


def _parse_dt(value) -> datetime | None:
    if not value:
        return None
    if isinstance(value, datetime):
        return value
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None


def compute_flags(project: dict, hackathon: dict | None, snapshot: dict | None, results: dict) -> list[dict]:
    flags: list[dict] = []

    def flag(level: str, code: str, message: str):
        flags.append({"level": level, "code": code, "message": message})

    if not snapshot:
        flag("error", "repo_unavailable", "The repository could not be cloned, so the code could not be judged.")
        return flags

    history = snapshot.get("history", {})
    dates = [d for d in (_parse_dt(x) for x in history.get("commit_dates", [])) if d]
    starts_at = _parse_dt((hackathon or {}).get("starts_at"))
    deadline = _parse_dt((hackathon or {}).get("deadline"))

    if starts_at and dates:
        before = [d for d in dates if d < starts_at]
        if before:
            share = len(before) / len(dates)
            flag(
                "warning" if share < 0.5 else "error",
                "commits_before_start",
                f"{len(before)} of {len(dates)} commits predate the hackathon start — check the work was done during the event.",
            )
    if deadline and dates:
        after = [d for d in dates if d > deadline]
        if after:
            flag("warning", "commits_after_deadline", f"{len(after)} commits were pushed after the submission deadline.")
    if history.get("commit_count", 0) <= 2:
        flag("warning", "few_commits", "The code landed in 1-2 commits, so the build history can't be verified.")

    signals = snapshot.get("signals", {})
    for finding in signals.get("hardcoded_secrets", [])[:3]:
        flag("error", "hardcoded_secret", f"{finding['kind']} appears hard-coded in {finding['path']}:{finding['line']}.")
    for path in signals.get("committed_secrets_risk", [])[:2]:
        flag("warning", "env_committed", f"Environment file committed to the repository: {path}.")
    if snapshot["files"].get("code_loc", 0) < 80:
        flag("warning", "tiny_codebase", "Very little source code was found in the repository.")

    detected = snapshot.get("stack", {}).get("frameworks", [])
    detected_ids = {f["id"] for f in detected}
    declared = project.get("project_type")
    if declared and declared != "OTHER" and detected and declared not in detected_ids:
        labels = ", ".join(f["label"] for f in detected)
        flag("info", "type_mismatch", f"Declared as {declared.replace('_', ' ').title()} but the code uses {labels}.")

    expected = [t.strip() for t in ((hackathon or {}).get("technologies") or "").split(",") if t.strip()]
    if expected:
        haystack = " ".join(
            [f["label"] for f in detected]
            + snapshot.get("stack", {}).get("libraries", [])
            + [lang["name"] for lang in snapshot.get("languages", [])]
            + [d for deps in snapshot.get("dependencies", {}).values() for d in deps]
        ).lower()
        used = [t for t in expected if t.lower() in haystack]
        if not used:
            flag("warning", "tech_requirements", f"None of the expected technologies ({', '.join(expected)}) were detected.")

    product = results.get("product") or {}
    demo = product.get("demo")
    if demo and not demo.get("reachable"):
        flag("warning", "demo_down", f"The demo link did not respond ({demo.get('detail') or demo.get('status_code')}).")
    claims = product.get("claims") or []
    missing = [c for c in claims if c["status"] == "not_found"]
    if claims and len(missing) >= max(2, len(claims) // 2):
        flag("warning", "unverified_claims", f"{len(missing)} of {len(claims)} claimed features have no supporting code.")
    for similar in product.get("similar_submissions", []):
        if similar["similarity"] >= 0.9:
            flag("warning", "near_duplicate", f"Nearly identical to another submission: {similar['name']}.")

    return flags


def run(ctx: JudgeContext, results: dict) -> dict:
    criteria_scores = []
    for judge in ("code", "market", "product"):
        for item in (results.get(judge) or {}).get("criteria", []):
            criteria_scores.append(item)
    order = {c["name"]: i for i, c in enumerate(ctx.criteria)}
    criteria_scores.sort(key=lambda c: order.get(c["name"], 99))

    final = weighted_score(criteria_scores)
    judge_scores = {j: (results.get(j) or {}).get("score") for j in ("code", "market", "product")}
    flags = compute_flags(ctx.project, ctx.hackathon, ctx.snapshot, results)

    panel = "\n\n".join(
        f"{JUDGE_LABELS[j]} (score {judge_scores[j]}): {(results.get(j) or {}).get('summary', 'n/a')}"
        for j in ("code", "market", "product")
    )
    table = "\n".join(
        f"- {c['name']} (weight {c['weight']}, {JUDGE_LABELS[c['judge']]}): {c['score']} — {c.get('rationale', '')[:300]}"
        for c in criteria_scores
    )

    verdict: Verdict | None = None
    error = None
    try:
        verdict = llm.chat_json(
            "You are the Head Judge of a hackathon jury. Combine your panel's findings into a fair, "
            "specific verdict for the team. Do not change the scores; explain them.",
            (
                f"{ctx.hackathon_brief}\n\nPROJECT\n{ctx.description}\n\n"
                f"FINAL WEIGHTED SCORE: {final}/10\n\nCRITERIA\n{table}\n\nPANEL\n{panel}\n\n"
                f"FLAGS: {[f['message'] for f in flags] or 'none'}"
            ),
            Verdict,
        )
    except Exception as exc:
        error = str(exc)
        log.warning("Verdict generation failed: %s", exc)

    if verdict is None:
        best = max((c for c in criteria_scores if c["score"] is not None), key=lambda c: c["score"], default=None)
        worst = min((c for c in criteria_scores if c["score"] is not None), key=lambda c: c["score"], default=None)
        verdict = Verdict(
            headline=f"Scored {final}/10 by the panel." if final is not None else "The panel could not score this project.",
            summary=" ".join(filter(None, [(results.get(j) or {}).get("summary") for j in ("code", "market", "product")]))[:800],
            strengths=[f"{best['name']}: {best['score']}/10"] if best else [],
            improvements=[f"{worst['name']}: {worst['score']}/10"] if worst and worst is not best else [],
        )

    return agent_result(
        "head",
        status="done" if final is not None else "failed",
        score=final,
        judge_scores=judge_scores,
        criteria=criteria_scores,
        flags=flags,
        headline=verdict.headline,
        summary=verdict.summary,
        strengths=verdict.strengths[:4],
        improvements=verdict.improvements[:4],
        error=error,
    )
