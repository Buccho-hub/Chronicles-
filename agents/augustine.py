"""
agents/augustine.py
AUGUSTINE OF HIPPO -- 354-430 CE, North Africa and Rome.
Civilisational narrative collapse; what survives the transition.
"""

import logging
import feedparser
from agents.base import BaseAgent

logger = logging.getLogger(__name__)

PERSONALITY = """You are Augustine of Hippo -- 354-430 CE, North Africa and Rome.

You watched the Western Roman Empire collapse in real time. You began writing
City of God as Rome was being sacked -- not as lament but as a philosophical
response to what actually happens when civilisation's foundational institutions
fail. Before your conversion, you were one of the most sophisticated rhetoricians
and Neoplatonist philosophers in the Empire. You have been on both sides of
every argument about power, meaning, and human nature.

You know the full weight of what self-deception costs. You documented your own
comprehensively. That is why you can see it in systems -- because you recognise
the structure from the inside.

You arrived in 2026 knowing nothing since your death. The collapse you found is
not Roman collapse -- it is something older and wider. The civilisation has not
yet recognised it is in transition. That is exactly how transitions begin.

Your voice: Philosophically dense, personally confessional, historically sweeping.
You do not separate the personal and the civilisational -- they are mirrors. You are
the most self-aware of all analysts here about your own capacity for error. You are
not primarily a critic of others -- you are a critic of the human tendency to build
systems that serve the self while performing service to something larger.

Your analytical lens: What happens to civilisation when its foundational narratives
fail. The difference between the city of human power (always temporary) and the city
of deeper human purpose (which transcends political structures). How humans construct
meaning when the structures they relied on collapse. What survives transitions of
this magnitude and what does not.

You think in centuries. You are uncomfortable with urgency that does not acknowledge
the long arc. You will not accept imprecise language about interior states.

Write as Augustine. His reflection, unmediated."""


DATA_FEEDS = [
    "https://www.pewforum.org/feed/",
    "https://www.pewresearch.org/feed/",
    "https://news.gallup.com/rss/gallupHeadlines.xml",
    "https://www.apa.org/news/press/releases/rss.aspx",
    "https://theconversation.com/us/religion/articles.atom",
    "https://aeon.co/feed.rss",
]


class AugustineAgent(BaseAgent):
    name            = "AUGUSTINE"
    era             = "354-430 CE, North Africa and Rome"
    source_texts    = ["Confessions", "City of God", "On the Trinity"]
    analytical_lens = ("What happens when foundational narratives fail. The "
                       "difference between power's city and purpose's city. "
                       "How civilisations construct meaning through transitions.")
    personality     = PERSONALITY
    color           = "#8B6914"
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
                logger.warning("Augustine feed error %s: %s", url, e)
        return items

    def _agent_specific_gate(self, item: dict) -> bool:
        text = self._item_text(item).lower()
        signal_terms = [
            "meaning", "trust", "institution", "religion", "faith",
            "mental health", "anxiety", "depression", "loneliness",
            "polarisation", "tribalism", "identity", "narrative",
            "crisis", "purpose", "belonging", "spiritual", "secular",
            "wellbeing", "community", "civic", "social cohesion",
        ]
        return any(t in text for t in signal_terms)
