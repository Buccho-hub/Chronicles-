"""
agents/base.py
BaseAgent -- three-stage cognition: gate -> score -> think.
All agents inherit from this.

UPDATES:
  - SCORE_THRESHOLD raised to 0.38 (was delegated to MINIMUM_SCORE=0.05 -- effectively zero)
  - _passes_local_gate: hard-reject boilerplate, image descriptions, About-page content
  - _build_user_prompt: explicit instruction to extract structural signal, not describe source
  - think(): prompt now requests a distinct HEADLINE: line so extraction is reliable
  - _extract_headline: reads the explicit HEADLINE: tag instead of first sentence of body
  - _extract_tags: extended tag map with finer categories
"""

import re
import logging
from abc import ABC, abstractmethod
from database import get_db
from signal_integrity import score_item
from agents.llm_gateway import get_gateway

logger = logging.getLogger(__name__)

# Minimum SIL score to spend an LLM call.
# 0.05 (original) was effectively zero -- almost any item passes.
# 0.38 filters to items with at least moderate consequence + density.
DISPATCH_THRESHOLD = 0.38

# Hard-reject patterns: content that is structurally useless as intelligence
_REJECT_PATTERNS = [
    # Image/visual descriptions being fed as text
    r"the image (presented|shows|depicts|is)",
    r"(photo|photograph|image|picture) (of|showing|depicting)",
    r"caption:",
    # About-page / institutional boilerplate
    r"(about us|our mission|we are a|we're a|founded in \d{4})",
    r"(subscribe|newsletter|sign up|log in|create an account)",
    r"(privacy policy|terms of (service|use)|cookie)",
    # Pure press release openers with no signal
    r"^(for immediate release|press release|media contact)",
    # Job listings / event listings
    r"(job title|apply now|closing date|salary range)",
    r"(register now|event details|tickets available)",
]

_REJECT_RE = [re.compile(p, re.IGNORECASE) for p in _REJECT_PATTERNS]

# Minimum meaningful content length
_MIN_TEXT_LENGTH = 80


class BaseAgent(ABC):
    name:            str = ""
    era:             str = ""
    source_texts:    list[str] = []
    analytical_lens: str = ""
    personality:     str = ""        # full system prompt
    color:           str = "#C9A84C"
    territory:       str = ""        # economic / geopolitical / social / systemic

    MAX_THINK_CALLS_PER_RUN: int = 6
    SCORE_THRESHOLD: float = DISPATCH_THRESHOLD

    # -- Abstract interface --------------------------------------------------

    @abstractmethod
    def fetch_data(self) -> list[dict]:
        """Return raw items from domain-specific sources."""

    def _agent_specific_gate(self, item: dict) -> bool:
        """Override in subclasses for domain-specific filtering."""
        return True

    # -- Stage 1: local gate (no API) ----------------------------------------

    def _passes_local_gate(self, item: dict) -> bool:
        text = self._item_text(item).strip()

        # Reject trivially short content
        if len(text) < _MIN_TEXT_LENGTH:
            return False

        # Reject known-useless content patterns
        for pattern in _REJECT_RE:
            if pattern.search(text[:500]):
                logger.debug("[%s] gate rejected (pattern): %.80s", self.name, text)
                return False

        return self._agent_specific_gate(item)

    # -- Stage 2: signal scoring ---------------------------------------------

    def _score_signal(self, item: dict) -> dict:
        return score_item(item, agent_name=self.name)

    # -- Stage 3: LLM synthesis ----------------------------------------------

    def think(self, item: dict, memory_block: str = "") -> dict | None:
        gw = get_gateway()
        db = get_db()

        item_id = self._item_id(item)
        if db.is_seen(item_id, self.name):
            return None

        context_block = self._build_context_block(memory_block)
        user_prompt   = self._build_user_prompt(item)

        raw = gw.call(
            agent       = self.name,
            system      = self.personality,
            user        = context_block + "\n\n" + user_prompt,
            max_tokens  = 900,
            temperature = 0.72,
        )

        if not raw:
            return None

        db.mark_seen(item_id, self.name)

        dispatch = {
            "type":     "dispatch",
            "agent":    self.name,
            "body":     _strip_headline_prefix(raw),
            "headline": _extract_headline(raw),
            "tags":     _extract_tags(raw),
            "raw_data": item,
        }
        return dispatch

    # -- Orchestrator --------------------------------------------------------

    def run(self) -> list[dict]:
        db = get_db()
        logger.info("[%s] run starting", self.name)

        try:
            items = self.fetch_data()
        except Exception as exc:
            logger.error("[%s] fetch_data failed: %s", self.name, exc)
            items = []

        items_fetched = len(items)

        # Stage 1 -- local gate
        gated = [i for i in items if self._passes_local_gate(i)]
        logger.info("[%s] %d/%d passed local gate", self.name, len(gated), items_fetched)

        # Stage 2 -- score; rank descending; apply raised threshold
        scored = []
        for item in gated:
            result = self._score_signal(item)
            if result["sil_score"] >= self.SCORE_THRESHOLD:
                scored.append((result["sil_score"], result, item))

        scored.sort(key=lambda x: x[0], reverse=True)
        logger.info("[%s] %d passed SIL threshold (%.2f)", self.name, len(scored), self.SCORE_THRESHOLD)

        # Stage 3 -- think (capped)
        recent       = db.get_dispatches(limit=5, agent_filter=self.name)
        memory_block = self._build_memory_block(recent)

        produced    = []
        think_calls = 0

        for sil, sig_result, item in scored:
            if think_calls >= self.MAX_THINK_CALLS_PER_RUN:
                break
            dispatch = self.think(item, memory_block=memory_block)
            if dispatch:
                dispatch["sil_score"]  = sil
                dispatch["dimensions"] = sig_result["dimensions"]
                dispatch_id = db.save_dispatch(dispatch)
                dispatch["id"] = dispatch_id
                produced.append(dispatch)
                think_calls += 1

        db.log_agent_run(self.name, items_fetched, len(scored), len(produced))
        logger.info("[%s] produced %d dispatches", self.name, len(produced))
        return produced

    # -- Helpers -------------------------------------------------------------

    @staticmethod
    def _item_text(item: dict) -> str:
        parts = []
        for f in ("title", "headline", "body", "summary", "description", "content"):
            v = item.get(f)
            if v and isinstance(v, str):
                parts.append(v)
        return " ".join(parts)

    @staticmethod
    def _item_id(item: dict) -> str:
        for f in ("id", "url", "link", "guid"):
            v = item.get(f)
            if v:
                return str(v)[:200]
        import hashlib, json
        return hashlib.sha256(json.dumps(item, sort_keys=True).encode()).hexdigest()[:40]

    def _build_memory_block(self, recent: list[dict]) -> str:
        if not recent:
            return ""
        parts = ["[YOUR RECENT DISPATCHES -- for context, do not repeat these]"]
        for d in recent[:3]:
            body = d.get("body", "")[:200]
            parts.append(f"-- {body}...")
        return "\n".join(parts)

    def _build_context_block(self, memory: str) -> str:
        lines = [
            f"You are {self.name}, {self.era}.",
            f"Analytical lens: {self.analytical_lens}",
        ]
        if memory:
            lines.append("\n" + memory)
        return "\n".join(lines)

    def _build_user_prompt(self, item: dict) -> str:
        text = self._item_text(item)
        source_url = item.get("link", item.get("url", ""))
        source_hint = f"\nSource: {source_url}" if source_url else ""

        return (
            f"[INCOMING DATA SIGNAL]{source_hint}\n{text[:2000]}\n\n"
            "Your task: extract the structural signal beneath this data -- not describe the source.\n\n"
            "Rules:\n"
            "  1. Do NOT summarise or describe what the article/source says. That is not a dispatch.\n"
            "  2. Identify the underlying structural condition the data reveals.\n"
            "  3. Draw the specific ancient parallel from your own era -- name the mechanism.\n"
            "  4. State what this implies for the next 6-18 months.\n"
            "  5. If this data carries no genuine structural signal, respond with exactly: NO_SIGNAL\n\n"
            "Format your response as:\n"
            "HEADLINE: [one precise falsifiable sentence, max 120 chars]\n"
            "[Dispatch body: 120-300 words. Begin with the structural observation. "
            "No preamble, no 'this article', no 'the data signal reveals'.]\n"
        )


# -- Module-level extraction functions (used by think()) ---------------------

def _extract_headline(raw: str) -> str:
    """
    Read the explicit HEADLINE: tag from the LLM response.
    Falls back to first meaningful line if tag absent.
    """
    for line in raw.strip().splitlines():
        line = line.strip()
        if line.upper().startswith("HEADLINE:"):
            return line[9:].strip()[:120]

    # Fallback: first non-empty line that doesn't look like metadata
    for line in raw.strip().splitlines():
        line = line.strip()
        if len(line) > 20 and not line.upper().startswith(("NO_SIGNAL", "FORMAT", "RULES")):
            return line[:120]

    return raw[:120]


def _strip_headline_prefix(raw: str) -> str:
    """
    Remove the HEADLINE: line from the body so they don't duplicate.
    """
    lines = raw.strip().splitlines()
    body_lines = []
    for line in lines:
        if line.strip().upper().startswith("HEADLINE:"):
            continue
        body_lines.append(line)
    return "\n".join(body_lines).strip()


def _extract_tags(text: str) -> list[str]:
    lower = text.lower()
    tag_map = {
        "economy":       ["gdp", "inflation", "market", "economic", "trade", "debt", "fiscal", "monetary"],
        "power":         ["empire", "government", "political", "geopolit", "military", "hegemony", "sovereignty"],
        "technology":    ["ai", "algorithm", "surveillance", "digital", "data", "automation", "cyber"],
        "ecology":       ["climate", "biodiversity", "ecological", "environment", "carbon", "species"],
        "health":        ["health", "disease", "mental", "pharmaceutical", "epidemic", "mortality"],
        "inequality":    ["wage", "wealth", "poverty", "housing", "food insecurity", "disparity", "redistribution"],
        "institutions":  ["institution", "trust", "governance", "regulatory", "legitimacy", "accountability"],
        "migration":     ["refugee", "migrant", "diaspora", "displacement", "asylum", "border"],
        "finance":       ["bank", "credit", "currency", "interest rate", "bond", "capital"],
        "social":        ["protest", "movement", "community", "civil society", "identity", "cohesion"],
        "supply_chain":  ["supply chain", "logistics", "shortage", "procurement", "commodity"],
        "information":   ["propaganda", "censorship", "media", "narrative", "disinformation", "press"],
    }
    return [tag for tag, keywords in tag_map.items()
            if any(k in lower for k in keywords)]
