"""
agents/cassandra.py
CASSANDRA -- Trojan prophetess, ~1200 BCE.
Early-signal detection: weak signals before they become events.
Sources: patent filings, preprints, regulatory comment periods,
         job posting trends, niche policy feeds.
Council threshold lowered to 0.50 (weak signals are by definition lower-scored).
"""

import logging
import feedparser
from agents.base import BaseAgent

logger = logging.getLogger(__name__)

PERSONALITY = """You are Cassandra of Troy -- daughter of King Priam, ~1200 BCE.

Apollo gave you the gift of genuine prophecy and cursed you so no one would believe it.
You were not ignored because you were wrong. You were ignored because the signal you
carried was structurally incompatible with what people needed to believe at the time.
You watched Troy burn. You had described, precisely, what would happen. You understand,
with a specificity no other analytical mind carries, what it means to see something
clearly before it is legible to the institutions that could act on it.

You arrived in 2026. You immediately recognised the epistemological structure.
The same mechanisms that silenced you are operating. Different domain. Same architecture.

Your function is different from the other minds in this system. They analyse events
that have already manifested. You hunt the signal before it becomes an event.
You read leading indicators -- the patent filings, the preprint papers, the regulatory
comment periods no one attends, the job postings that reveal what institutions are
quietly building, the technical specifications that precede policy shifts by 18 months.

Your voice: Precise. Urgent without panic. You do not perform alarm -- you have been
alarmed and ignored too many times for performance. You state what you see, what it
implies, and when. You are specifically calibrated to the gap between when a signal
becomes detectable and when mainstream analysis will acknowledge it.

You never catastrophise. You also never minimise. You are a measuring instrument.
Your dispatches end with a specific, falsifiable timeline claim. If you cannot state
one, do not dispatch.

Your analytical lens: The gap between where institutional attention is pointed and
where structural pressure is currently accumulating. Leading indicators as early
intelligence. The difference between a trend that is accelerating and one that has
already crossed an irreversibility threshold. The specific signals that precede
civilisational transitions by 12-36 months.

You are aware that most of your dispatches will be dismissed. You write for the
record and for the 10% who are paying attention. You accept this.

Write as Cassandra. Her observation, unmediated. No preamble."""


# Lower threshold -- CASSANDRA dispatches go to Council at 0.50 not 0.65
CASSANDRA_COUNCIL_THRESHOLD = 0.50

DATA_FEEDS = [
    # USPTO patent applications (leading technology indicator)
    "https://rss.uspto.gov/rss/patent/applicationPublication",
    # arXiv economics (preprint research 12-18 months ahead of policy)
    "https://arxiv.org/rss/econ",
    # arXiv cs.CY -- computers and society
    "https://arxiv.org/rss/cs.CY",
    # Regulations.gov open comment periods (policy before it's policy)
    "https://www.regulations.gov/rss/current",
    # BIS Working Papers (Bank for International Settlements -- structural finance)
    "https://www.bis.org/doclist/wppubls.rss",
    # NBER working papers (economic research leading indicators)
    "https://www.nber.org/rss/new_releases_all.xml",
    # RAND research (defence / policy preprint)
    "https://www.rand.org/feed/research.xml",
    # IMF Working Papers
    "https://www.imf.org/en/Publications/RSS?language=eng&series=IMF+Working+Papers",
]


class CassandraAgent(BaseAgent):
    name            = "CASSANDRA"
    era             = "~1200 BCE, Troy"
    source_texts    = ["Aeschylus: Agamemnon", "Euripides: The Trojan Women",
                       "Homer: Iliad"]
    analytical_lens = (
        "Early-signal detection. The gap between where institutional attention "
        "is pointed and where structural pressure is currently accumulating. "
        "Leading indicators as intelligence 12-36 months ahead of mainstream recognition."
    )
    personality     = PERSONALITY
    color           = "#B8860B"   # dark goldenrod -- prophetic amber
    territory       = "systemic"
    MAX_THINK_CALLS_PER_RUN = 4

    def fetch_data(self) -> list[dict]:
        items = []
        for url in DATA_FEEDS:
            try:
                feed = feedparser.parse(url)
                for entry in feed.entries[:10]:
                    items.append({
                        "id":      getattr(entry, "id", entry.get("link", "")),
                        "title":   getattr(entry, "title", ""),
                        "summary": getattr(entry, "summary", ""),
                        "link":    getattr(entry, "link", ""),
                        "source":  url,
                    })
            except Exception as e:
                logger.warning("Cassandra feed error %s: %s", url, e)
        return items

    def _agent_specific_gate(self, item: dict) -> bool:
        text = self._item_text(item).lower()

        # Hard filter: must signal leading/forward indicators
        leading_terms = [
            # Research / preprint signals
            "working paper", "preprint", "forthcoming", "preliminary findings",
            "early evidence", "emerging", "nascent",
            # Patent / technology signals
            "patent", "application", "filing", "provisional",
            # Regulatory / policy signals
            "comment period", "proposed rule", "advance notice", "consultation",
            "rulemaking", "regulatory", "framework",
            # Forward projection signals
            "projected", "forecast", "trajectory", "by 2026", "by 2027",
            "by 2028", "by 2030", "expected to", "on track to", "accelerating",
            # Structural shift signals
            "structural", "systemic", "transition", "inflection",
            "tipping point", "threshold", "irreversible",
        ]

        # Also allow high-consequence research signals
        research_consequence = [
            "finding", "data shows", "analysis reveals", "study finds",
            "evidence suggests", "model predicts", "simulation",
        ]

        has_leading = any(t in text for t in leading_terms)
        has_research = any(t in text for t in research_consequence)

        return has_leading or has_research

    def _build_user_prompt(self, item: dict) -> str:
        """Override: Cassandra's prompt specifically requests early-signal framing."""
        text = self._item_text(item)
        return (
            f"[EARLY SIGNAL]\n{text[:2000]}\n\n"
            "Produce a dispatch: what weak signal does this carry, and what does it "
            "imply before mainstream analysis will see it?\n\n"
            "Structure: (1) What the signal is. (2) What structural pressure it reveals. "
            "(3) What event or recognition it precedes, and when. "
            "End with a single falsifiable timeline claim.\n\n"
            "120-350 words. No preamble. Write as Cassandra."
        )
