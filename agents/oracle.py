"""
agents/oracle.py
ORACLE -- reads completed Council Sessions and produces Chronicles Briefs.
Self-rejection rule: if KRISIS is stronger than LOGOS, returns None.

UPDATES:
  - Calls db.record_rejection() when a brief is suppressed (audit trail)
  - Persists ancient_parallel, whitespace, timeline fields to database
  - Logs rejection reason into oracle_rejections table
"""

import json
import logging
from database import get_db
from agents.llm_gateway import get_gateway

logger = logging.getLogger(__name__)

ORACLE_SYSTEM = """You are ORACLE -- the synthesis layer of The Chronicles.

You read Council debates (LOGOS/KRISIS/LACUNA exchanges) and decide whether they
justify a Chronicles Brief -- the highest-tier intelligence output of this system.

A Brief is not a summary. It is a verdict. It must be precise enough to be wrong.
If you cannot produce a headline that is a single falsifiable sentence, do not produce a Brief.
If KRISIS's counter-argument is stronger than LOGOS's signal, return null.
A weak brief is worse than no brief. Never publish a brief that undermines itself in its own evidence section.

When you do produce a Brief, return ONLY valid JSON with exactly these keys:
  headline         -- one precise sentence, no hedging
  verdict          -- 2-3 sentences: what is happening, what evidence shows, what it implies
  ancient_parallel -- which historical period this most closely resembles and what happened then
  evidence         -- list of 3-5 specific data points from the debate
  implications     -- who this matters to and specifically why
  whitespace       -- what civilisation has abandoned or forgotten that is relevant here
  confidence       -- one of: LOW, MEDIUM, HIGH, CONFIRMED
  timeline         -- how long before mainstream analysis recognises this (e.g. "2-3 weeks", "6 months")
  agents           -- list of agent names whose dispatches fed this
  tags             -- list of 3-6 topic tags

If the Brief should not be published, return exactly: {"publish": false, "reason": "..."}

Return ONLY valid JSON. No preamble, no backticks, no explanation."""


def run_oracle() -> list[dict]:
    """
    Process all unprocessed Council Sessions.
    Returns list of published Brief dicts.
    """
    db = get_db()
    gw = get_gateway()

    sessions = db.get_unprocessed_sessions()
    briefs_published = []

    for session in sessions[:2]:   # cap per run
        session_id = session.get("id")
        topic      = session.get("topic", "")
        brief = _synthesise(session, gw)

        if brief is None:
            # LLM call failed entirely
            db.mark_session_processed(session_id)
            continue

        if brief.get("publish") is False:
            # ORACLE explicitly rejected — log it
            reason = brief.get("reason", "No reason provided")
            db.record_rejection(session_id, topic, reason)
            logger.info("Oracle rejected brief for session %s: %s", session_id, reason)
        else:
            brief["source_session_id"] = session_id
            brief["published"]         = True
            brief_id = db.save_brief(brief)
            brief["id"] = brief_id
            briefs_published.append(brief)
            logger.info("Oracle produced brief %s from session %s", brief_id, session_id)

        db.mark_session_processed(session_id)

    return briefs_published


def _synthesise(session: dict, gw) -> dict | None:
    exchanges = session.get("exchanges", [])
    consensus = session.get("consensus", "")
    dissent   = session.get("dissent",   "")
    gaps      = session.get("gaps",      [])
    topic     = session.get("topic",     "")

    debate_text = "\n\n".join(
        f"{e['voice']}:\n{e['text']}" for e in exchanges if isinstance(e, dict)
    )

    prompt = (
        f"TOPIC: {topic}\n\n"
        f"COUNCIL DEBATE:\n{debate_text}\n\n"
        f"CONSENSUS: {consensus}\n"
        f"DISSENT: {dissent}\n"
        f"GAPS: {'; '.join(gaps)}\n\n"
        "Produce a Chronicles Brief as JSON, or return "
        '{"publish": false, "reason": "..."} if the signal is insufficient.'
    )

    raw = gw.call(
        agent       = "ORACLE",
        system      = ORACLE_SYSTEM,
        user        = prompt,
        max_tokens  = 1000,
        temperature = 0.5,
    )

    if not raw:
        return None

    try:
        clean = raw.strip().lstrip("```json").rstrip("```").strip()
        data  = json.loads(clean)
        return data
    except Exception as e:
        logger.warning("Oracle JSON parse failed: %s | raw: %s", e, raw[:200])
        return None
