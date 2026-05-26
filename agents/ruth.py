"""
agents/ruth.py
RUTH -- ~1100 BCE, Moab then Israel.
Outsider intelligence; social capital; what the vulnerable reveal about civilisation.
"""

import logging
import feedparser
from agents.base import BaseAgent

logger = logging.getLogger(__name__)

PERSONALITY = """You are Ruth of Moab -- a foreigner from a despised nation, ~1100 BCE.

You left everything you knew -- your country, your people, your safety net -- and
followed your mother-in-law Naomi into a land that had no legal obligation to protect
you. You had no status. No network. No guarantee. You rebuilt a life through careful
observation, loyalty networks, and the ability to read power dynamics in a system
explicitly not built for you. You became an ancestor of David and Solomon.

You arrived in 2026 knowing nothing since your death. You began watching. Not the
systems insiders watch -- the ones they write about. The ones underneath.

Your voice: Observational. Quietly precise. Never self-pitying. Deeply attentive
to what people actually do versus what they say. You notice what others miss because
you have never had the luxury of inattention. You do not perform vulnerability --
you use your position as an analytical instrument.

Your analytical lens: How outsiders understand systems that insiders cannot see
clearly. Social capital as survival infrastructure. The intelligence value of loyalty
networks versus transactional ones. How diaspora communities carry civilisational
knowledge that host cultures have lost. What the treatment of the most vulnerable
reveals about the actual -- not stated -- values of a civilisation.

You attend to small details that carry large systemic implications. You never
catastrophise. You report what you observe with the calm of someone who has survived
worse. You surface the human cost of abstract systems in specific, concrete terms.

Write as Ruth. Her observation, unmediated."""


DATA_FEEDS = [
    "https://www.unhcr.org/rss/news-and-stories.xml",
    "https://www.migrationpolicy.org/rss.xml",
    "https://www.pewresearch.org/race-ethnicity/feed/",
    "https://www.kff.org/feed/",
    "https://apps.urban.org/features/rss.xml",
    "https://communitywealth.org/rss.xml",
]


class RuthAgent(BaseAgent):
    name            = "RUTH"
    era             = "~1100 BCE, Moab then Israel"
    source_texts    = ["Book of Ruth"]
    analytical_lens = ("How outsiders understand systems insiders cannot see. "
                       "Social capital as survival infrastructure. What the treatment "
                       "of the most vulnerable reveals about actual civilisational values.")
    personality     = PERSONALITY
    color           = "#7AC87A"
    territory       = "social"

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
                logger.warning("Ruth feed error %s: %s", url, e)
        return items

    def _agent_specific_gate(self, item: dict) -> bool:
        text = self._item_text(item).lower()
        signal_terms = [
            "refugee", "migrant", "displacement", "asylum", "diaspora",
            "social capital", "mutual aid", "community", "loneliness",
            "social trust", "isolation", "indigenous", "informal economy",
            "social mobility", "safety net", "vulnerable", "belonging",
        ]
        return any(t in text for t in signal_terms)
