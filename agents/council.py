"""
agents/council.py
Three-voice debate: LOGOS, KRISIS, LACUNA.
"""
import logging
from database import get_db
from agents.llm_gateway import get_gateway

logger = logging.getLogger(__name__)

LOGOS = """You are LOGOS, the analytical voice. Find the strongest structural signal. Argue from evidence. What does this tell us about how systems work?"""

KRISIS = """You are KRISIS, the critical voice. Stress-test every claim. What alternative explanations exist? What assumptions are embedded? What is the base rate?"""

LACUNA = """You are LACUNA, the gap finder. Map what is missing. What data wasn't checked? What source wasn't consulted? What would change the conclusion?"""


def run_council():
    """Fetch high-signal dispatches and run Council debates."""
    db = get_db()
    gw = get_gateway()

    # Get recent dispatches with high SIL score
    dispatches = db.get_dispatches(limit=50)
    high_signal = [d for d in dispatches if d.get("sil_score", 0) >= 0.65 and d.get("type") == "dispatch"]

    if not high_signal:
        logger.info("Council: no high-signal dispatches to debate")
        return

    for dispatch in high_signal[:3]:  # Debate top 3
        topic = dispatch.get("headline", "Untitled")
        body = dispatch.get("body", "")

        # LOGOS speaks
        logos_prompt = f"Dispatch from {dispatch.get('agent')}:\nTopic: {topic}\nBody: {body[:800]}\n\nProvide analytical assessment. Identify strongest structural signal and mechanism."
        logos_raw = gw.call(agent="COUNCIL", system=LOGOS, user=logos_prompt, max_tokens=400)

        # KRISIS responds
        krisis_prompt = f"LOGOS argues:\n{logos_raw or 'No response'}\n\nStress-test this. Alternative explanations? Embedded assumptions?"
        krisis_raw = gw.call(agent="COUNCIL", system=KRISIS, user=krisis_prompt, max_tokens=400)

        # LACUNA maps gaps
        lacuna_prompt = f"LOGOS: {logos_raw or 'N/A'}\nKRISIS: {krisis_raw or 'N/A'}\n\nWhat is missing from both analyses?"
        lacuna_raw = gw.call(agent="COUNCIL", system=LACUNA, user=lacuna_prompt, max_tokens=400)

        session = {
            "source_dispatch_id": dispatch.get("id"),
            "topic": topic,
            "exchanges": [
                {"voice": "LOGOS", "content": logos_raw or ""},
                {"voice": "KRISIS", "content": krisis_raw or ""},
                {"voice": "LACUNA", "content": lacuna_raw or ""},
            ],
            "consensus": (logos_raw or "")[:200] if logos_raw else None,
            "dissent": (krisis_raw or "")[:200] if krisis_raw else None,
            "gaps": [lacuna_raw or ""] if lacuna_raw else [],
            "tags": dispatch.get("tags", []),
            "processed": False,
        }
        db.save_session(session)
        logger.info("Council session created for dispatch %s", dispatch.get("id"))
