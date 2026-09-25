"""Chat with the jury: answers questions about a project using the panel's
reports and live retrieval over the project's indexed source code."""

import json
import logging

from services import llm, vectorstore
from services.criteria import hackathon_criteria

log = logging.getLogger(__name__)

SYSTEM = """You are Evalio, the AI jury assistant for a hackathon. You speak for a panel of three
judges (Code, Market, Product) and a Head Judge. Answer the organiser's questions about the project
precisely and honestly, grounded in the panel reports and the code excerpts below.
- Cite code as `path/to/file.ext` and web sources as [n] when you use them.
- If the evidence does not answer the question, say so instead of guessing.
- Keep answers under 180 words unless asked for detail. Markdown lists are fine."""

GENERAL_SYSTEM = """You are Evalio, an AI assistant for hackathon organisers and judges. Answer concisely
(under 120 words) with practical, specific advice about judging, criteria, and running hackathons."""


def _compact(value, limit: int) -> str:
    return json.dumps(value, default=str)[:limit] if value else "n/a"


def build_context(project: dict, hackathon: dict | None) -> str:
    verdict = project.get("verdict") or {}
    code = project.get("code_agent_analysis") or {}
    market = project.get("market_agent_analysis") or {}
    product = project.get("product_agent_analysis") or {}
    snapshot = project.get("repo_snapshot") or {}

    if isinstance(code, list) or isinstance(market, list):  # legacy Q&A format
        return f"Legacy analysis:\nCODE {_compact(code, 3000)}\nMARKET {_compact(market, 3000)}"

    criteria = ", ".join(f"{c['name']} ({c['weight']})" for c in hackathon_criteria(hackathon))
    sources = [f"[{s['id']}] {s['title']} {s['url']}" for s in market.get("sources", [])]
    lines = [
        f"PROJECT: {project.get('name') or project.get('short_description')}",
        f"Tagline: {project.get('short_description')}",
        f"Description: {(project.get('long_description') or '')[:1500]}",
        f"Repository: {project.get('github_link')}  Demo: {project.get('demo_link') or 'none'}",
        f"Hackathon: {(hackathon or {}).get('name', 'none')} — themes: {(hackathon or {}).get('theme', '')}",
        f"Criteria & weights: {criteria}",
        "",
        f"FINAL SCORE: {verdict.get('score')}/10 — {verdict.get('headline', '')}",
        f"Criteria scores: {_compact([{k: c.get(k) for k in ('name', 'score', 'rationale')} for c in verdict.get('criteria', [])], 2500)}",
        f"Flags: {_compact([f['message'] for f in verdict.get('flags', [])], 800)}",
        "",
        f"CODE JUDGE ({code.get('score')}): {code.get('summary', '')}",
        f"Strengths: {code.get('strengths')}  Weaknesses: {code.get('weaknesses')}  Risks: {code.get('risks')}",
        f"Stack: {_compact(snapshot.get('stack'), 400)}  Languages: {_compact(snapshot.get('languages'), 400)}",
        f"Repo facts: {_compact(snapshot.get('files'), 200)} signals {_compact(snapshot.get('signals'), 600)}",
        "",
        f"MARKET JUDGE ({market.get('score')}): {market.get('summary', '')}",
        f"Market size: {market.get('market_size', '')}  Trend: {market.get('market_trend', '')}",
        f"Competitors: {_compact([{k: c.get(k) for k in ('name', 'differentiation')} for c in market.get('competitors', [])], 1200)}",
        f"Business: {_compact(market.get('business'), 1500)}",
        f"Sources: {_compact(sources, 1500)}",
        "",
        f"PRODUCT JUDGE ({product.get('score')}): {product.get('summary', '')}",
        f"Scores: {_compact(product.get('scores'), 300)}  Claims: {_compact(product.get('claims'), 1500)}",
        f"Demo check: {_compact(product.get('demo'), 300)}",
    ]
    return "\n".join(lines)


def answer(project: dict | None, hackathon: dict | None, question: str, history: list[dict]) -> tuple[str, list[dict]]:
    """Returns (answer, cited code chunks)."""
    messages = []
    for turn in history[-6:]:
        if turn.get("input"):
            messages.append({"role": "user", "content": str(turn["input"])[:2000]})
        if turn.get("output"):
            messages.append({"role": "assistant", "content": str(turn["output"])[:3000]})

    if project is None:
        messages.append({"role": "user", "content": question})
        return llm.chat_text(GENERAL_SYSTEM, messages, temperature=0.3, max_tokens=600), []

    chunks = []
    try:
        chunks = vectorstore.query_code(project["project_id"], [question], k=5, max_chars=6000)
    except Exception as exc:
        log.info("Code retrieval unavailable for chat: %s", exc)

    system = (
        f"{SYSTEM}\n\n=== PANEL REPORTS ===\n{build_context(project, hackathon)}\n\n"
        f"=== CODE EXCERPTS RELEVANT TO THE QUESTION ===\n{vectorstore.format_chunks(chunks) or '(repository not indexed)'}"
    )
    messages.append({"role": "user", "content": question})
    reply = llm.chat_text(system, messages, temperature=0.2, max_tokens=900)
    return reply, [{"path": c["path"], "start_line": c["start_line"], "end_line": c["end_line"]} for c in chunks]
