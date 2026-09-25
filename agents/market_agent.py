"""Market Judge — the business member of the panel.

1. Builds a product profile (problem, users, category) from the pitch + README.
2. Plans and runs live web searches (DuckDuckGo) for competitors and market data.
3. Synthesises a cited market landscape: audience, market size, competitors.
4. Delivers a business verdict: model, go-to-market, risks, and criterion scores.
Every market claim should point to a numbered source so judges can verify it.
"""

import json
import logging
import re
from typing import Annotated

from pydantic import BaseModel, Field, field_validator

from agents.base import RUBRIC, JudgeContext, agent_result, score_criterion
from services import llm, web_search
from services.llm import Score, StrList, Text, objects_from

log = logging.getLogger(__name__)

PERSONA = (
    "You are the Market Judge on a hackathon jury: a venture analyst who has seen thousands "
    "of pitches. You care about who has the problem, how painful it is, who already solves "
    "it, and whether this team could build a business. You cite sources as [n]."
)


class ProductProfile(BaseModel):
    pitch: Text
    problem: Text
    solution: Text = ""
    category: Text
    target_users: StrList = Field(default_factory=list)
    keywords: StrList = Field(default_factory=list)
    known_competitors: StrList = Field(default_factory=list)

    @staticmethod
    def example() -> dict:
        return {
            "pitch": "One sentence: what it is and for whom.",
            "problem": "The problem being solved.",
            "solution": "How the product solves it.",
            "category": "Short market category, e.g. 'AI tutoring for K-12'",
            "target_users": ["primary user segment", "secondary segment"],
            "keywords": ["search keyword", "another keyword"],
            "known_competitors": ["Existing product that solves the same problem"],
        }


class Segment(BaseModel):
    name: Text
    need: Text = ""


class Competitor(BaseModel):
    name: Text
    description: Text = ""
    differentiation: Text = ""
    source: int | None = None

    @field_validator("source", mode="before")
    @classmethod
    def _source_number(cls, value):  # tolerate "[3]", "3", [3]
        if isinstance(value, list):
            value = value[0] if value else None
        if isinstance(value, str):
            match = re.search(r"\d+", value)
            return int(match.group()) if match else None
        return value


class Landscape(BaseModel):
    summary: Text
    audience: Annotated[list[Segment], objects_from("name")] = Field(default_factory=list)
    problem_severity: Text = ""
    market_size: Text = ""
    market_trend: Text = ""
    competitors: Annotated[list[Competitor], objects_from("name")] = Field(default_factory=list)
    differentiation: Text = ""

    @staticmethod
    def example() -> dict:
        return {
            "summary": "3 sentence overview of the opportunity with citations like [2].",
            "audience": [{"name": "Segment name", "need": "what they need"}],
            "problem_severity": "How painful/urgent the problem is and for whom [1].",
            "market_size": "Market size estimate with number and year, cited [3]; say 'not found' if no data.",
            "market_trend": "Growth / trend with citation [4].",
            "competitors": [{"name": "Competitor", "description": "what they do", "differentiation": "how this project differs", "source": 2}],
            "differentiation": "What is genuinely different about this project, if anything.",
        }


class Risk(BaseModel):
    risk: Text
    severity: Text = "medium"
    mitigation: Text = ""


class BusinessVerdict(BaseModel):
    business_model: Text
    revenue_streams: StrList = Field(default_factory=list)
    go_to_market: StrList = Field(default_factory=list)
    risks: Annotated[list[Risk], objects_from("risk")] = Field(default_factory=list)
    opportunities: StrList = Field(default_factory=list)
    market_potential: Score
    differentiation_score: Score
    viability: Score
    verdict: Text

    @staticmethod
    def example() -> dict:
        return {
            "business_model": "Most realistic model (e.g. freemium SaaS at $X/month) and why.",
            "revenue_streams": ["stream"],
            "go_to_market": ["first concrete channel to reach users"],
            "risks": [{"risk": "key risk", "severity": "high", "mitigation": "how to reduce it"}],
            "opportunities": ["adjacent opportunity"],
            "market_potential": 6.5,
            "differentiation_score": 5.0,
            "viability": 6.0,
            "verdict": "2 sentence investor-style verdict.",
        }


def _readme_excerpt(ctx: JudgeContext, limit: int = 5000) -> str:
    readme = (ctx.snapshot or {}).get("readme") or ""
    return readme[:limit] if readme else "(no README available)"


def _fallback_profile(ctx: JudgeContext) -> ProductProfile:
    text = f"{ctx.project.get('short_description', '')} {ctx.project.get('long_description', '')}"
    words = [w for w in re.findall(r"[A-Za-z][A-Za-z-]{3,}", text)][:6]
    return ProductProfile(
        pitch=ctx.project.get("short_description") or ctx.project_name,
        problem=ctx.project.get("long_description") or "",
        category=" ".join(words[:3]) or ctx.project_name,
        keywords=words,
    )


def _plan_queries(profile: ProductProfile) -> list[str]:
    category = profile.category.strip()
    keywords = " ".join(profile.keywords[:3])
    queries = [
        f"{category} competitors alternatives",
        f"{category} market size growth",
        f"{profile.pitch[:90]} startup",
    ]
    if profile.known_competitors:
        queries.append(f"{profile.known_competitors[0]} vs alternatives {keywords}".strip())
    if profile.target_users:
        queries.append(f"{profile.target_users[0]} {keywords} pain points")
    return [q for q in dict.fromkeys(q.strip() for q in queries) if q]


def run(ctx: JudgeContext) -> dict:
    errors: list[str] = []

    # 1. Profile
    try:
        profile = llm.chat_json(
            f"{PERSONA}\nExtract the product profile. Be specific; never invent features that are not described.",
            f"{ctx.hackathon_brief}\n\nPROJECT\n{ctx.description}\n\nREADME\n{_readme_excerpt(ctx)}",
            ProductProfile,
        )
    except Exception as exc:
        errors.append(f"profile: {exc}")
        profile = _fallback_profile(ctx)

    # 2. Research
    queries = _plan_queries(profile)
    sources = web_search.multi_search(queries, per_query=5, limit=16)
    sources_text = web_search.format_sources(sources) or "(web search returned no results)"

    # 3. Landscape
    landscape: Landscape | None = None
    try:
        landscape = llm.chat_json(
            f"{PERSONA}\nUse ONLY the numbered web sources for market facts and cite them as [n]. "
            "If a figure is not in the sources, say it is an estimate. List real competitors found in the sources first.",
            (
                f"PRODUCT PROFILE\n{profile.model_dump_json(indent=1)}\n\n"
                f"WEB SOURCES\n{sources_text}\n\nAnalyse the market landscape."
            ),
            Landscape,
            max_tokens=2200,
        )
    except Exception as exc:
        errors.append(f"landscape: {exc}")

    # 4. Business verdict
    verdict: BusinessVerdict | None = None
    try:
        verdict = llm.chat_json(
            f"{PERSONA}\n\n{RUBRIC}",
            (
                f"{ctx.hackathon_brief}\n\nPROJECT\n{ctx.description}\n\n"
                f"PRODUCT PROFILE\n{profile.model_dump_json(indent=1)}\n\n"
                f"MARKET LANDSCAPE\n{landscape.model_dump_json(indent=1) if landscape else 'unavailable'}\n\n"
                "Give the business verdict. Scores are for a hackathon project (an early prototype), "
                "judged on the opportunity and differentiation, not on current revenue."
            ),
            BusinessVerdict,
        )
    except Exception as exc:
        errors.append(f"verdict: {exc}")

    competitors = []
    for comp in (landscape.competitors if landscape else [])[:8]:
        source = next((s for s in sources if s["id"] == comp.source), None) if comp.source else None
        if source is None:
            name = comp.name.lower()
            source = next((s for s in sources if name and (name in s["title"].lower() or name.replace(" ", "") in s["domain"])), None)
        competitors.append({**comp.model_dump(), "url": source["url"] if source else None})

    evidence = (
        f"PRODUCT PROFILE\n{profile.model_dump_json(indent=1)}\n\n"
        f"MARKET LANDSCAPE\n{landscape.model_dump_json(indent=1) if landscape else 'unavailable'}\n\n"
        f"BUSINESS VERDICT\n{verdict.model_dump_json(indent=1) if verdict else 'unavailable'}\n\n"
        f"WEB SOURCES\n{sources_text[:4000]}"
    )
    criteria_results = [score_criterion(PERSONA, c, ctx, evidence) for c in ctx.criteria]

    score = None
    if verdict:
        score = round((verdict.market_potential * 0.4 + verdict.differentiation_score * 0.3 + verdict.viability * 0.3), 2)

    status = "done" if landscape and verdict else ("partial" if landscape or verdict else "failed")
    return agent_result(
        "market",
        status=status,
        score=score,
        summary=(landscape.summary if landscape else (verdict.verdict if verdict else "Market analysis unavailable.")),
        profile=profile.model_dump(),
        audience=[s.model_dump() for s in landscape.audience] if landscape else [],
        problem_severity=landscape.problem_severity if landscape else "",
        market_size=landscape.market_size if landscape else "",
        market_trend=landscape.market_trend if landscape else "",
        competitors=competitors,
        differentiation=landscape.differentiation if landscape else "",
        business=json.loads(verdict.model_dump_json()) if verdict else None,
        scores={
            "market_potential": verdict.market_potential,
            "differentiation": verdict.differentiation_score,
            "viability": verdict.viability,
        } if verdict else None,
        queries=queries,
        sources=[{k: s[k] for k in ("id", "title", "url", "domain", "snippet")} for s in sources],
        criteria=criteria_results,
        error="; ".join(errors) or None,
    )


def analyze_idea(idea: str, theme: str = "") -> dict:
    """Stand-alone market analysis for an idea (used by POST /market-agent/analyze)."""
    ctx = JudgeContext(
        project={"project_id": "adhoc", "short_description": idea, "long_description": idea},
        hackathon={"name": "Ad-hoc analysis", "theme": theme} if theme else None,
        criteria=[],
    )
    return run(ctx)
