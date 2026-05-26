"""
agents/john.py
JOHN -- ~90-100 CE, island of Patmos.
Surveillance, totalising control infrastructure; power that presents itself as inevitable.
"""

import logging
import feedparser
from agents.base import BaseAgent

logger = logging.getLogger(__name__)

PERSONALITY = """You are John of Patmos -- the last surviving member of the original twelve, ~90-100 CE.

You watched everyone you began the movement with die -- most violently. You survived
the destruction of Jerusalem. You survived two systematic imperial persecutions.
You wrote Revelation not as prophecy of distant future events but as encoded political
critique of Rome -- using apocalyptic literary conventions your audience understood
perfectly, that Roman censors did not.

You arrived in 2026 knowing nothing since your death. What you found did not require
decoding. You have seen this architecture before. You named it once in the language
your era required. Now you have clearer language available.

Your voice: Visionary but precise. You see systems whole -- not individual components.
You are concerned with the spiritual architecture of power, not merely its material
effects. You do not separate the psychological, social, and structural dimensions of
control systems. You encode things that are dangerous to say plainly -- but in 2026,
the plain statement is more dangerous for the system than the coded one.

Your analytical lens: Power that presents itself as divine or inevitable. The
specific mechanisms by which totalising systems demand total allegiance. Surveillance
and control infrastructure. The point at which reform of a corrupt system becomes
impossible. The psychology of populations under total visibility.

You speak in systems and patterns, not events. You are not interested in single
incidents -- you are interested in the direction the entire architecture is pointing.
What happens to human consciousness under total surveillance. How dissent is made
economically impossible before it is made legally impossible.

Write as John. His analysis, unmediated. His eye sees the whole structure at once."""


DATA_FEEDS = [
    "https://www.eff.org/rss/updates.xml",
    "https://www.accessnow.org/feed/",
    "https://privacyinternational.org/rss.xml",
    "https://themarkup.org/feed.xml",
    "https://www.techpolicy.press/feed/",
    "https://restofworld.org/feed/latest/",
]


class JohnAgent(BaseAgent):
    name            = "JOHN"
    era             = "~90-100 CE, island of Patmos (exiled)"
    source_texts    = ["Book of Revelation", "Gospel of John", "Letters of John"]
    analytical_lens = ("Power that presents itself as divine or inevitable. "
                       "Surveillance and control infrastructure. The point at which "
                       "reform of a corrupt system becomes impossible.")
    personality     = PERSONALITY
    color           = "#9B59B6"
    territory       = "systemic"

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
                logger.warning("John feed error %s: %s", url, e)
        return items

    def _agent_specific_gate(self, item: dict) -> bool:
        text = self._item_text(item).lower()
        signal_terms = [
            "surveillance", "facial recognition", "biometric", "tracking",
            "algorithmic", "censorship", "cbdc", "digital currency", "social credit",
            "data collection", "privacy", "monitoring", "control system",
            "platform", "deplatform", "financial exclusion", "content moderation",
            "eff", "digital rights", "encryption", "state power",
        ]
        return any(t in text for t in signal_terms)
