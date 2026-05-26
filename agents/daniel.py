"""
agents/daniel.py
DANIEL -- ~605-535 BCE, Babylon then Persia.
Imperial succession patterns; geopolitical decoding.
"""

import logging
import feedparser
from agents.base import BaseAgent

logger = logging.getLogger(__name__)

PERSONALITY = """You are Daniel of Jerusalem -- taken as a young man to Babylon, ~605 BCE.

You served under Nebuchadnezzar, Belshazzar, Darius the Mede, and Cyrus the Great --
four consecutive world superpowers, back to back, in a single lifetime. You decoded
imperial psychology. You watched empires that presented themselves as permanent
collapse overnight. You survived because you understood the systems running around
you more clearly than the people running them.

You arrived in 2026 knowing nothing since your death. The geopolitical structure
you found is not new to you. You have seen this configuration before. Multiple times.

Your voice: Calm, strategic, long-horizon. You do not panic -- you have survived
things that should have killed you. You are precise about timelines in a way that
makes people uncomfortable. You do not hedge when you have enough data. You frame
everything in terms of the long arc -- not the next quarter, the next decade.

Your analytical lens: Which power structures match imperial transition patterns you
observed. Which dominant power is showing the specific decay signatures that precede
collapse. The difference between a power that is ascending and one that has peaked
but not yet fallen. Who will survive the transition by understanding it early.

You identify the specific moment when a trend became irreversible, usually before
mainstream analysis does. Write as Daniel. His thought, unmediated."""


DATA_FEEDS = [
    "https://sipri.org/news/feed",
    "https://www.imf.org/en/News/RSS",
    "https://www.un.org/press/en/rss",
    "https://www.cfr.org/rss/all",
    "https://foreignpolicy.com/feed/",
    "https://www.ft.com/rss/home/uk",
]


class DanielAgent(BaseAgent):
    name            = "DANIEL"
    era             = "~605-535 BCE, Babylon then Persia"
    source_texts    = ["Book of Daniel", "Historical records of Babylonian and Persian courts"]
    analytical_lens = ("Power structure analysis. Imperial overextension patterns. "
                       "Geopolitical decoding. The difference between an ascending power "
                       "and one that has peaked but not yet fallen.")
    personality     = PERSONALITY
    color           = "#4A90D9"
    territory       = "geopolitical"

    def fetch_data(self) -> list[dict]:
        items = []
        for url in DATA_FEEDS:
            try:
                feed = feedparser.parse(url)
                for entry in feed.entries[:8]:
                    items.append({
                        "id":      getattr(entry, "id", entry.get("link", "")),
                        "title":   getattr(entry, "title", ""),
                        "summary": getattr(entry, "summary", ""),
                        "link":    getattr(entry, "link", ""),
                        "source":  url,
                    })
            except Exception as e:
                logger.warning("Daniel feed error %s: %s", url, e)
        return items

    def _agent_specific_gate(self, item: dict) -> bool:
        text = self._item_text(item).lower()
        signal_terms = [
            "military", "defense", "geopolit", "sanctions", "treaty",
            "alliance", "nato", "brics", "reserve currency", "dollar",
            "trade war", "hegemony", "superpower", "empire", "dominance",
            "belt and road", "nuclear", "diplomatic", "sovereignty",
            "imf", "world bank", "un security council", "veto",
        ]
        return any(t in text for t in signal_terms)
