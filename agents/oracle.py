"""
agents/oracle.py
Synthesis into Chronicles Briefs.
"""
import logging
from database import get_db
from agents.llm_gateway import get_gateway

logger = logging.getLogger(__name__)

ORACLE_SYSTEM = """You are the ORACLE. Read Council Sessions and produce Chronicles Briefs.

A Brief must include:
- headline: One precise sentence. No hedging.
- verdict: 2-3 sentences. What is happening, what the evidence shows, what it implies.
- ancient_parallel: Which historical period does this resemble? What happened then?
- evidence: 3-5 specific data points.
- implications: Who does this matter to and specifically why.
- whitespace: What has civilisation abandoned that is relevant here?
- confidence: LOW / MEDIUM / HIGH / CONFIRMED
- timeline: How long before this becomes obvious to mainstream analysis?

If KRISIS's counter-argument is stronger than LOGOS's signal, return null. A weak brief is worse than no brief."""


def run_oracle():
    """Read unprocessed Council Sessions and produce Briefs."""
    db = get_db()
    gw = get_gateway()

    sessions = db.get_unprocessed_sessions()
    if not sessions:
        logger.info("Oracle: no unprocessed sessions")
        return

    for session in sessions:
        exchanges = session.get("exchanges", [])
        topic = session.get("topic", "Untitled")

        # Build prompt from session
        debate_text = "\n\n".join(
            f"[{ex.get('voice')}]: {ex.get('content', '')[:400]}"
            for ex in exchanges
        )

        user_prompt = f"Council Session on: {topic}\n\n{debate_text}\n\nProduce a Chronicles Brief."

        raw = gw.call(agent="ORACLE", system=ORACLE_SYSTEM, user=user_prompt, max_tokens=800)
        if not raw:
            logger.warning("Oracle produced no brief for session %s", session.get("id"))
            db.mark_session_processed(session.get("id"))
            continue

        # Parse brief from raw text (simplified — in production use structured output)
        brief = {
            "source_session_id": session.get("id"),
            "headline": raw.split("\n")[0][:200] if raw else "Untitled Brief",
            "verdict": raw[:500] if raw else "",
            "evidence": [ex.get("content", "")[:150] for ex in exchanges if ex.get("content")],
            "implications": "See verdict.",
            "action_items": [],
            "confidence": "MEDIUM",
            "tier": "free",
            "agents": [session.get("topic", "COUNCIL")],
            "tags": session.get("tags", []),
            "published": True,
            "ancient_parallel": "",
            "timeline": "",
            "whitespace": "",
        }
        db.save_brief(brief)
        db.mark_session_processed(session.get("id"))
        logger.info("Brief created for session %s", session.get("id"))
