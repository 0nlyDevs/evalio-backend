"""Hackathon judging criteria: parsing, weights and routing to the judge agent
best placed to score each criterion."""

import re
from typing import Any

JUDGES = ("code", "market", "product")

JUDGE_LABELS = {
    "code": "Code Judge",
    "market": "Market Judge",
    "product": "Product Judge",
}

DEFAULT_CRITERIA = [
    {"name": "Technical Execution", "weight": 30, "judge": "code",
     "description": "Quality, architecture and completeness of the implementation."},
    {"name": "Innovation", "weight": 25, "judge": "product",
     "description": "Originality of the idea and of the approach."},
    {"name": "Market Potential", "weight": 25, "judge": "market",
     "description": "Size of the opportunity, differentiation and business viability."},
    {"name": "Theme Alignment", "weight": 20, "judge": "product",
     "description": "How well the project answers the hackathon theme."},
]

_ROUTING_KEYWORDS: dict[str, list[str]] = {
    "code": [
        "code", "quality", "technical", "tech", "architecture", "scalab", "security", "secure",
        "performance", "test", "documentation", "docs", "stack", "implementation", "engineering",
        "complexity", "maintainab", "best practice", "execution", "robust", "api", "infra",
        "devops", "clean", "reliab", "algorithm", "data model", "backend", "frontend",
    ],
    "market": [
        "market", "business", "commercial", "revenue", "monetiz", "monetis", "viab", "impact",
        "social", "adoption", "customer", "competit", "startup", "sustainab", "environment",
        "economic", "go-to-market", "traction", "growth", "value proposition", "feasib",
    ],
    "product": [
        "innovat", "creativ", "original", "novel", "idea", "theme", "relevan", "alignment",
        "design", "ux", "ui", "usab", "user experience", "presentation", "pitch", "demo",
        "complete", "functional", "feature", "wow", "polish", "accessib", "problem",
    ],
}


def route_criterion(name: str) -> str:
    lowered = name.lower()
    scores = {judge: 0 for judge in JUDGES}
    for judge, keywords in _ROUTING_KEYWORDS.items():
        for keyword in keywords:
            if re.search(rf"(^|[^a-z]){re.escape(keyword)}", lowered):
                scores[judge] += len(keyword)  # longer matches are more specific
    best = max(scores, key=lambda j: scores[j])
    return best if scores[best] > 0 else "product"


def normalize_criteria(raw: Any) -> list[dict]:
    """Accepts a comma separated string, a list of names or a list of dicts."""
    items: list[dict] = []
    if raw is None or raw == "" or raw == []:
        return [dict(c) for c in DEFAULT_CRITERIA]
    if isinstance(raw, str):
        raw = [part for part in raw.split(",")]
    for entry in raw:
        if isinstance(entry, str):
            entry = {"name": entry}
        if not isinstance(entry, dict):
            continue
        name = str(entry.get("name", "")).strip()[:80]
        if not name or any(i["name"].lower() == name.lower() for i in items):
            continue
        try:
            weight = float(entry.get("weight", 1) or 1)
        except (TypeError, ValueError):
            weight = 1.0
        judge = entry.get("judge")
        items.append({
            "name": name,
            "weight": max(0.0, min(100.0, weight)),
            "judge": judge if judge in JUDGES else route_criterion(name),
            "description": str(entry.get("description", "") or "").strip()[:300],
        })
    if not items:
        return [dict(c) for c in DEFAULT_CRITERIA]
    if all(i["weight"] == 0 for i in items):
        for i in items:
            i["weight"] = 1.0
    return items


def hackathon_criteria(hackathon: dict | None) -> list[dict]:
    if not hackathon:
        return [dict(c) for c in DEFAULT_CRITERIA]
    if hackathon.get("criteria_config"):
        return normalize_criteria(hackathon["criteria_config"])
    return normalize_criteria(hackathon.get("criteria") or "")


def criteria_names(criteria: list[dict]) -> str:
    return ", ".join(c["name"] for c in criteria)


def weighted_score(criteria_scores: list[dict]) -> float | None:
    """Weighted mean over scored criteria (0..10). Unscored criteria are excluded
    and their weight is redistributed, so one failing agent can't zero a project."""
    scored = [c for c in criteria_scores if c.get("score") is not None and c.get("weight", 0) > 0]
    total_weight = sum(c["weight"] for c in scored)
    if not scored or total_weight == 0:
        return None
    return round(sum(c["score"] * c["weight"] for c in scored) / total_weight, 2)
