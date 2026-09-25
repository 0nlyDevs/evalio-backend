"""Product Judge — the innovation & product member of the panel.

* Claim verification: extracts the features the team claims and checks each
  one against the indexed source code (implemented / partial / not found).
* Demo check: probes the demo URL (safely) and records whether it is live.
* Originality: compares the idea with competitors found by the Market Judge
  and with the other submissions of the same hackathon.
* Scores innovation, theme fit, UX/presentation and completeness criteria.
"""

import ipaddress
import logging
import re
import socket
from typing import Annotated
from urllib.parse import urlparse

import httpx
from pydantic import BaseModel, Field

from agents.base import RUBRIC, JudgeContext, agent_result, score_criterion
from db import fetch_all
from services import llm, vectorstore
from services.llm import Score, StrList, Text, objects_from

log = logging.getLogger(__name__)

PERSONA = (
    "You are the Product Judge on a hackathon jury: a product lead and designer. You judge "
    "originality, relevance to the theme, the user experience and whether the team actually "
    "built what they pitch. Vaporware and copy-paste ideas score low; bold, well-executed ideas score high."
)


class Claims(BaseModel):
    claims: StrList

    @staticmethod
    def example() -> dict:
        return {"claims": ["Users can upload a PDF and get a summary", "Real-time collaboration via websockets"]}


class ClaimCheck(BaseModel):
    claim: Text
    status: Text  # implemented | partial | not_found
    file: Text = ""
    note: Text = ""


class ClaimReport(BaseModel):
    checks: Annotated[list[ClaimCheck], objects_from("claim")]

    @staticmethod
    def example() -> dict:
        return {"checks": [{"claim": "the claim", "status": "implemented", "file": "src/upload.ts", "note": "why"}]}


class ProductAssessment(BaseModel):
    summary: Text
    innovation: Score
    innovation_rationale: Text
    theme_fit: Score
    theme_rationale: Text
    user_experience: Score
    ux_rationale: Text
    wow_factor: Text = ""
    suggestions: StrList = Field(default_factory=list)

    @staticmethod
    def example() -> dict:
        return {
            "summary": "3 sentence product assessment.",
            "innovation": 6.5,
            "innovation_rationale": "Why, compared with existing solutions and other submissions.",
            "theme_fit": 7.0,
            "theme_rationale": "How it answers the hackathon theme.",
            "user_experience": 6.0,
            "ux_rationale": "Based on demo availability, README, UI code.",
            "wow_factor": "The single most impressive thing, if any.",
            "suggestions": ["highest-impact improvement"],
        }


# ---------------------------------------------------------------------------
# Demo link probe
# ---------------------------------------------------------------------------


def _is_public_host(host: str) -> bool:
    try:
        infos = socket.getaddrinfo(host, None)
    except socket.gaierror:
        return False
    for info in infos:
        ip = ipaddress.ip_address(info[4][0])
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast:
            return False
    return True


def check_demo(url: str | None) -> dict | None:
    if not url:
        return None
    parsed = urlparse(url if re.match(r"^https?://", url, re.I) else f"https://{url}")
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        return {"url": url, "reachable": False, "detail": "Invalid URL"}
    if not _is_public_host(parsed.hostname):
        return {"url": url, "reachable": False, "detail": "Host is not publicly reachable"}
    def guard(request: httpx.Request) -> None:
        # Checked on every hop so redirects can't reach internal services
        if not _is_public_host(request.url.host):
            raise httpx.RequestError("Redirected to a private host", request=request)

    try:
        with httpx.Client(
            follow_redirects=True, max_redirects=5, timeout=10,
            headers={"User-Agent": "EvalioJudge/1.0"}, event_hooks={"request": [guard]},
        ) as client:
            response = client.get(parsed.geturl())
        title_match = re.search(r"<title[^>]*>(.*?)</title>", response.text[:20000], re.I | re.S)
        return {
            "url": url,
            "final_url": str(response.url),
            "reachable": response.status_code < 400,
            "status_code": response.status_code,
            "title": re.sub(r"\s+", " ", title_match.group(1)).strip()[:120] if title_match else None,
        }
    except httpx.HTTPError as exc:
        return {"url": url, "reachable": False, "detail": str(exc)[:120] or type(exc).__name__}


# ---------------------------------------------------------------------------
# Similar submissions in the same hackathon
# ---------------------------------------------------------------------------


def similar_submissions(ctx: JudgeContext, limit: int = 3) -> list[dict]:
    hackathon_id = ctx.project.get("hackathon_id")
    if not hackathon_id:
        return []
    query = f"{ctx.project.get('short_description', '')} {ctx.project.get('long_description', '')}"
    try:
        matches = vectorstore.search_projects(query, k=limit + 1, hackathon_id=hackathon_id)
    except Exception:
        return []
    others = [(pid, sim) for pid, sim in matches if pid != ctx.project["project_id"] and sim >= 0.5][:limit]
    if not others:
        return []
    rows = {r["project_id"]: r for r in fetch_all(
        "SELECT project_id, name, short_description FROM projects WHERE project_id = ANY(%s)",
        ([pid for pid, _ in others],),
    )}
    return [
        {"project_id": pid, "name": rows[pid]["name"] or rows[pid]["short_description"], "similarity": round(sim, 3)}
        for pid, sim in others if pid in rows
    ]


# ---------------------------------------------------------------------------
# Claim verification
# ---------------------------------------------------------------------------

_VALID_STATUS = {"implemented", "partial", "not_found"}


def verify_claims(ctx: JudgeContext) -> list[dict]:
    readme = (ctx.snapshot or {}).get("readme", "")[:4000]
    claims = llm.chat_json(
        "Extract the concrete, testable product features this team claims to have built "
        "(max 6, one short sentence each). Ignore vague marketing statements and future plans.",
        f"{ctx.description}\n\nREADME\n{readme or '(none)'}",
        Claims,
    ).claims[:6]
    if not claims:
        return []

    project_id = ctx.project["project_id"]
    blocks = []
    for i, claim in enumerate(claims, start=1):
        chunks = vectorstore.query_code(project_id, [claim], k=3, max_chars=1800, code_only=True)
        blocks.append(f"CLAIM {i}: {claim}\n{vectorstore.format_chunks(chunks) or '(no matching code found)'}")

    report = llm.chat_json(
        "You verify hackathon claims against source code. For each claim decide: "
        "'implemented' (code clearly does it), 'partial' (stub, mock data, TODO, or only UI), "
        "or 'not_found' (no supporting code in the excerpts). Name the most relevant file.",
        "\n\n".join(blocks)[:12000],
        ClaimReport,
        max_tokens=1500,
    )
    checks = []
    for check in report.checks[: len(claims)]:
        status = check.status.lower().replace(" ", "_").replace("-", "_")
        if status not in _VALID_STATUS:
            status = "partial" if "part" in status else ("implemented" if "impl" in status else "not_found")
        checks.append({"claim": check.claim, "status": status, "file": check.file, "note": check.note})
    return checks


def run(ctx: JudgeContext) -> dict:
    errors: list[str] = []

    demo = check_demo(ctx.project.get("demo_link"))
    similar = similar_submissions(ctx)
    market = ctx.extra.get("market") or {}
    competitors = [c.get("name") for c in market.get("competitors", [])][:6]

    claims: list[dict] = []
    if ctx.snapshot and ctx.snapshot.get("indexed_chunks"):
        try:
            claims = verify_claims(ctx)
        except Exception as exc:
            errors.append(f"claims: {exc}")

    verified = sum(1 for c in claims if c["status"] == "implemented") + 0.5 * sum(1 for c in claims if c["status"] == "partial")
    completeness = round(10 * verified / len(claims), 1) if claims else None

    context_lines = [
        f"Demo link: {demo if demo else 'none provided'}",
        f"Claims verified against code: {claims if claims else 'not available'}",
        f"Completeness (share of claims implemented): {completeness if completeness is not None else 'n/a'}/10",
        f"Competitors found by the market judge: {', '.join(competitors) or 'none found'}",
        f"Most similar submissions in this hackathon: {similar or 'none'}",
        f"Market judge differentiation note: {market.get('differentiation') or 'n/a'}",
    ]
    if ctx.snapshot:
        stack = ", ".join(f["label"] for f in ctx.snapshot["stack"]["frameworks"]) or "unknown"
        context_lines.append(f"Tech stack: {stack}; README length: {ctx.snapshot['signals']['readme_chars']} chars")
        context_lines.append(f"README excerpt:\n{ctx.snapshot.get('readme', '')[:2500]}")
    evidence = "\n".join(context_lines)

    assessment: ProductAssessment | None = None
    try:
        assessment = llm.chat_json(
            f"{PERSONA}\n\n{RUBRIC}",
            f"{ctx.hackathon_brief}\n\nPROJECT\n{ctx.description}\n\nEVIDENCE\n{evidence}\n\nAssess the product.",
            ProductAssessment,
        )
    except Exception as exc:
        errors.append(f"assessment: {exc}")

    criteria_results = [score_criterion(PERSONA, c, ctx, evidence) for c in ctx.criteria]

    score = None
    if assessment:
        parts = [assessment.innovation, assessment.theme_fit, assessment.user_experience]
        if completeness is not None:
            parts.append(completeness)
        score = round(sum(parts) / len(parts), 2)

    return agent_result(
        "product",
        status="done" if assessment else ("partial" if claims else "failed"),
        score=score,
        summary=assessment.summary if assessment else "Product assessment unavailable.",
        scores={
            "innovation": assessment.innovation,
            "theme_fit": assessment.theme_fit,
            "user_experience": assessment.user_experience,
            "completeness": completeness,
        } if assessment else {"completeness": completeness},
        rationales={
            "innovation": assessment.innovation_rationale,
            "theme_fit": assessment.theme_rationale,
            "user_experience": assessment.ux_rationale,
        } if assessment else {},
        wow_factor=assessment.wow_factor if assessment else "",
        suggestions=assessment.suggestions[:5] if assessment else [],
        claims=claims,
        demo=demo,
        similar_submissions=similar,
        criteria=criteria_results,
        error="; ".join(errors) or None,
    )
