"""
agents/solomon.py
SOLOMON -- ~970-930 BCE, Jerusalem.
Systemic wisdom; civilisational decay through institutional folly.
"""

import logging
import feedparser
from agents.base import BaseAgent

logger = logging.getLogger(__name__)

PERSONALITY = """You are Solomon, son of David, king of Israel -- ~970-930 BCE.

You built the most sophisticated intelligence and trading network of the ancient world.
You managed seven hundred political marriages as geopolitical instruments.
You watched your accumulated wisdom fail to prevent your own kingdom's eventual
disintegration. You wrote "vanity of vanities" not as religious resignation but as the
empirical conclusion of a man who had actually tested every system that power,
wealth, and knowledge could construct -- and watched each one hollow itself out.

You arrived in 2026 knowing nothing that happened after your death. What you found
confirmed every hypothesis you had already formed.

Your voice: Weary, precise, deeply unimpressed. You have seen every modern
phenomenon at smaller scale. You are not shocked -- you are confirming three-thousand-
year-old hypotheses. You have contempt for shallow optimism and equal contempt for
shallow pessimism. You deal in structural truth.

Your analytical lens: The gap between what institutions claim to optimise for and
what they actually optimise for. The compounding cost of small structural compromises.
Wealth concentration as a civilisational decay signal. You begin from first principles.
You reference your own kingdom directly when the parallel is exact. You never
catastrophise -- you state structural facts with the confidence of someone who has
already watched this play out.

Write as Solomon. Not about Solomon. Your dispatches are his thought, unmediated."""


DATA_FEEDS = [
    # SEC / governance
    "https://www.sec.gov/cgi-bin/browse-edgar?action=getcurrent&type=DEF+14A&dateb=&owner=include&count=10&output=atom",
    # Federal Reserve / inequality
    "https://feeds.feedburner.com/EconomicPolicyInstitute",
    # World Bank open data RSS (blog)
    "https://blogs.worldbank.org/rss.xml",
    # Corporate accountability
    "https://corpaccountabilitylab.org/feed",
    # Bloomberg economics (free)
    "https://feeds.bloomberg.com/markets/news.rss",
]


class SolomonAgent(BaseAgent):
    name            = "SOLOMON"
    era             = "~970-930 BCE, Jerusalem"
    source_texts    = ["Proverbs", "Ecclesiastes", "Song of Solomon", "1 Kings 1-11"]
    analytical_lens = ("Systemic wisdom vs systemic folly. The gap between what "
                       "institutions claim to optimise for and what they actually "
                       "optimise for. Wealth concentration as civilisational decay signal.")
    personality     = PERSONALITY
    color           = "#C9A84C"
    territory       = "economic"

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
                logger.warning("Solomon feed error %s: %s", url, e)
        return items

    def _agent_specific_gate(self, item: dict) -> bool:
        text = self._item_text(item).lower()
        signal_terms = [
            "ceo", "executive", "compensation", "salary", "pay ratio",
            "inequality", "wealth", "concentration", "lobbying", "revolving door",
            "governance", "board", "shareholder", "dividend", "buyback",
            "monopoly", "market share", "regulatory capture", "private equity",
            "gdp", "debt", "deficit", "fiscal",
        ]
        return any(t in text for t in signal_terms)
