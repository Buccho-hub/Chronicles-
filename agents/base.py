"""
agents/base.py
BaseAgent -- three-stage cognition: gate -> score -> think.
All agents inherit from this.
"""

import re
import logging
from abc import ABC, abstractmethod
from database import get_db
from signal_integrity import score_item, MINIMUM_SCORE
from agents.llm_gateway import get_gateway

logger = logging.getLogger(__name__)


class BaseAgent(ABC):
    name:           str = ""
    era:            str = ""
    source_texts:   list[str] = []
    analytical_lens:str = ""
    personality:    str = ""          # full system prompt
    color:          str = "#C9A84C"   # hex
    territory:      str = ""          # economic / geopolitical / social / systemic

    MAX_THINK_CALLS_PER_RUN: int = 8
    SCORE_THRESHOLD = MINIMUM_SCORE

    # -- Abstract interface --------------------------------------------------

    @abstractmethod
    def fetch_data(self) -> list[dict]:
        """Return raw items from domain-specific sources."""

    def _agent_specific_gate(self, item: dict) -> bool:
        """Override in subclasses for domain-specific filtering."""
        return True

    # -- Stage 1: local gate (no API) ----------------------------------------

    # Patterns that indicate media/image content rather than news
    _IMAGE_NOISE = [
        "the image presented", "the image shows", "the image depicts",
        "juxtaposition of the natural", "canoe, rainbow", "wind turbines coexisting",
        "photograph shows", "in the image,",
    ]

    def _passes_local_gate(self, item: dict) -> bool:
        text = self._item_text(item)
        if len(text.strip()) < 20:
            return False
        # Filter image/media descriptions that sneak through RSS feeds
        lower = text.lower()
        if any(p in lower for p in self._IMAGE_NOISE):
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
            "body":     raw,
            "headline": self._extract_headline(raw),
            "tags":     self._extract_tags(raw),
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

        # Stage 2 -- score; rank descending
        scored = []
        for item in gated:
            result = self._score_signal(item)
            if result["passes"]:
                scored.append((result["sil_score"], result, item))

        scored.sort(key=lambda x: x[0], reverse=True)
        logger.info("[%s] %d passed SIL threshold", self.name, len(scored))

        # Stage 3 -- think (capped)
        # Fetch recent context ONCE, not per think() call
        recent = db.get_dispatches(limit=5, agent_filter=self.name)
        memory_block = self._build_memory_block(recent)

        produced = []
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
        parts = ["[RECENT DISPATCHES -- your own recent analysis for context]"]
        for d in recent[:3]:
            body = d.get("body", "")[:300]
            parts.append(f"-- {body}...")
        return "\n".join(parts)

    def _build_context_block(self, memory: str) -> str:
        lines = [
            f"You are {self.name}.",
            f"Era: {self.era}",
            f"Analytical lens: {self.analytical_lens}",
        ]
        if memory:
            lines.append("\n" + memory)
        return "\n".join(lines)

    def _build_user_prompt(self, item: dict) -> str:
        text = self._item_text(item)
        return (
            f"[INCOMING DATA SIGNAL]\n{text[:2000]}\n\n"
            "Produce a dispatch: your genuine analysis of what this data reveals, "
            "measured against the patterns you observed in your own era. "
            "Begin with the structural observation. Then the ancient parallel. "
            "Then what it implies. 120-350 words. No preamble."
        )

    @staticmethod
    def _extract_headline(text: str) -> str:
        # First sentence, max 120 chars
        lines = text.strip().split("\n")
        for line in lines:
            line = line.strip()
            if len(line) > 20:
                return line[:120]
        return text[:120]

    @staticmethod
    def _extract_tags(text: str) -> list[str]:
        lower = text.lower()
        tag_map = {
            "economy":      ["gdp", "inflation", "market", "economic", "trade", "debt"],
            "power":        ["empire", "government", "political", "geopolit", "military"],
            "technology":   ["ai", "algorithm", "surveillance", "digital", "data"],
            "ecology":      ["climate", "biodiversity", "ecological", "environment"],
            "health":       ["health", "disease", "mental", "pharmaceutical"],
            "inequality":   ["wage", "wealth", "poverty", "housing", "food insecurity"],
            "institutions": ["institution", "trust", "governance", "regulatory"],
            "migration":    ["refugee", "migrant", "diaspora", "displacement"],
        }
        return [tag for tag, keywords in tag_map.items()
                if any(k in lower for k in keywords)]
