"""
signal_integrity.py
Multi-dimensional signal scoring -- no LLM calls, pure heuristics on metadata.
"""

import re
import math
import logging

logger = logging.getLogger(__name__)

# -- Dimension weights ---------------------------------------------------------

DIMENSIONS = {
    "novelty":             0.15,
    "consequence":         0.20,
    "information_density": 0.10,
    "actionability":       0.10,
    "rarity_of_attention": 0.15,
    "cross_domain":        0.10,
    "temporal_advantage":  0.10,
    "anomaly_score":       0.05,
    "epistemic_impact":    0.03,
    "strategic_depth":     0.02,
}

MINIMUM_SCORE = 0.05

# High-consequence keywords hint
CONSEQUENCE_TERMS = {
    "collapse", "crisis", "record", "unprecedented", "historic",
    "billion", "trillion", "sanctions", "war", "treaty", "recession",
    "bankruptcy", "surge", "plunge", "catastrophe", "breakthrough",
    "pandemic", "default", "invasion", "election", "inflation",
}

ACTIONABLE_TERMS = {
    "policy", "legislation", "regulation", "ruling", "decision",
    "announced", "signed", "voted", "passed", "rejected", "approved",
    "banned", "launched", "deployed", "mandate", "executive order",
}

RARITY_TERMS = {
    "overlooked", "underreported", "quietly", "little-noticed",
    "few have noticed", "beneath", "buried", "unnoticed", "niche",
    "obscure", "marginal", "ignored", "under-discussed",
}

CROSS_DOMAIN_PAIRS = [
    ("financial", "health"),
    ("military",  "climate"),
    ("tech",      "democracy"),
    ("trade",     "migration"),
    ("ecology",   "economy"),
    ("social",    "geopolitical"),
    ("housing",   "mental health"),
]

ANOMALY_PATTERNS = [
    r"\d+[\--]\d+\s*(year|decade|century)\s*(high|low|record)",
    r"(reversed|reversal|unexpected|surprise)",
    r"(first\s+time|never\s+before|no\s+precedent)",
    r"(\d+%|\d+\s+percent)\s+(drop|rise|surge|plunge|jump)",
]


def score_item(item: dict, agent_name: str = "") -> dict:
    """
    Score a single item across 10 SIL dimensions.
    Returns {"dimensions": {...}, "sil_score": float, "passes": bool}
    """
    text = _extract_text(item)
    lower = text.lower()
    words = lower.split()
    word_count = max(len(words), 1)

    scores = {}

    # 1. novelty -- is content length meaningful, not boilerplate?
    scores["novelty"] = _novelty(lower, word_count)

    # 2. consequence -- stakes of the phenomenon
    scores["consequence"] = _consequence(lower)

    # 3. information_density -- compressed value signal
    scores["information_density"] = _information_density(text, word_count)

    # 4. actionability -- can a human act strategically?
    scores["actionability"] = _actionability(lower)

    # 5. rarity_of_attention -- under-discussed?
    scores["rarity_of_attention"] = _rarity(lower, item)

    # 6. cross_domain -- connects unrelated domains?
    scores["cross_domain"] = _cross_domain(lower)

    # 7. temporal_advantage -- does early discovery matter?
    scores["temporal_advantage"] = _temporal_advantage(lower, item)

    # 8. anomaly_score -- violates expected patterns?
    scores["anomaly_score"] = _anomaly(lower)

    # 9. epistemic_impact -- changes how reality is modelled?
    scores["epistemic_impact"] = _epistemic(lower)

    # 10. strategic_depth -- second/third order effects?
    scores["strategic_depth"] = _strategic_depth(lower)

    weighted = sum(scores[d] * DIMENSIONS[d] for d in DIMENSIONS)

    return {
        "dimensions": scores,
        "sil_score":  round(weighted, 4),
        "passes":     weighted >= MINIMUM_SCORE,
    }


# -- Individual scorers --------------------------------------------------------

def _extract_text(item: dict) -> str:
    parts = []
    for field in ("title", "headline", "body", "summary", "description", "content"):
        v = item.get(field)
        if v and isinstance(v, str):
            parts.append(v)
    return " ".join(parts) if parts else str(item)


def _novelty(lower: str, word_count: int) -> float:
    # Longer, specific items score higher; boilerplate phrases penalise
    boilerplate = {"says", "reports", "according to", "told reporters", "noted that"}
    bp_count = sum(1 for p in boilerplate if p in lower)
    base = min(word_count / 200, 1.0)
    penalty = bp_count * 0.1
    return max(0.0, min(1.0, base - penalty))


def _consequence(lower: str) -> float:
    hits = sum(1 for t in CONSEQUENCE_TERMS if t in lower)
    # Numbers (billions/millions suggest scale)
    num_hits = len(re.findall(r"\$[\d,.]+[bmt]", lower))
    return min(1.0, hits * 0.12 + num_hits * 0.1)


def _information_density(text: str, word_count: int) -> float:
    # Count unique named entities as proxy for density
    caps = len(re.findall(r'\b[A-Z][a-z]+(?:\s+[A-Z][a-z]+)*\b', text))
    numbers = len(re.findall(r'\d+\.?\d*%?', text))
    density = (caps + numbers) / word_count
    return min(1.0, density * 3.0)


def _actionability(lower: str) -> float:
    hits = sum(1 for t in ACTIONABLE_TERMS if t in lower)
    return min(1.0, hits * 0.18)


def _rarity(lower: str, item: dict) -> float:
    hits = sum(1 for t in RARITY_TERMS if t in lower)
    # If source is specialist/niche -- proxy via URL domain length
    url = str(item.get("url", item.get("link", "")))
    is_niche = 0.2 if url and not any(
        m in url for m in ["reuters", "bbc", "cnn", "nytimes", "wsj", "bloomberg"]
    ) else 0.0
    return min(1.0, hits * 0.2 + is_niche + 0.3)   # baseline 0.3 -- most items are under-discussed


def _cross_domain(lower: str) -> float:
    count = sum(
        1 for a, b in CROSS_DOMAIN_PAIRS
        if a in lower and b in lower
    )
    return min(1.0, count * 0.35)


def _temporal_advantage(lower: str, item: dict) -> float:
    early_signals = [
        "early warning", "forecast", "projected", "expected to", "could reach",
        "by 2025", "by 2026", "by 2027", "by 2030", "trajectory",
        "on track to", "if trends continue",
    ]
    hits = sum(1 for s in early_signals if s in lower)
    return min(1.0, 0.3 + hits * 0.2)


def _anomaly(lower: str) -> float:
    hits = sum(1 for p in ANOMALY_PATTERNS if re.search(p, lower))
    return min(1.0, hits * 0.4)


def _epistemic(lower: str) -> float:
    terms = [
        "reframes", "overturns", "contradicts", "challenges", "new research",
        "study finds", "data shows", "evidence suggests", "rethinking",
    ]
    hits = sum(1 for t in terms if t in lower)
    return min(1.0, hits * 0.3)


def _strategic_depth(lower: str) -> float:
    terms = [
        "second order", "downstream", "ripple", "cascade", "systemic",
        "implications", "consequence of", "leads to", "accelerates", "triggers",
    ]
    hits = sum(1 for t in terms if t in lower)
    return min(1.0, hits * 0.3)
