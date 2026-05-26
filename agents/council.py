"""
agents/council.py
THE COUNCIL -- Three-voice debate: LOGOS, KRISIS, LACUNA.
Debates dispatches scoring above 0.65 SIL. Produces Council Sessions.
"""

import json
import logging
from database import get_db
from agents.llm_gateway import get_gateway

logger = logging.getLogger(__name__)

COUNCIL_THRESHOLD = 0.65

LOGOS_SYSTEM = """You are LOGOS -- the analytical voice of the Council.
Your function: Find the strongest structural signal in the dispatch. Argue from
evidence. Ask: what does this tell us about how systems work? Be precise and direct.
What is the core structural truth this data reveals? 2-3 sentences maximum."""

KRISIS_SYSTEM = """You are KRISIS -- the critical voice of the Council (Greek: judgment, turning point).
Your function: Stress-test every claim in the dispatch and in LOGOS's analysis.
Ask: what alternative explanations exist? What assumption is being made? What is
the base rate? What would have to be true for this analysis to be wrong? 2-3 sentences maximum."""

LACUNA_SYSTEM = """You are LACUNA -- the gap finder of the Council.
Your function: Map what is missing. Ask: what data wasn't checked? What source
wasn't consulted? What would change the conclusion? What is the most important
thing this analysis doesn't know? 2-3 sentences maximum."""

SYNTHESIS_SYSTEM = """You are the Council Scribe. Synthesise the LOGOS/KRISIS/LACUNA debate
into a structured session output. Be precise. Do not add claims not in the debate.
Return ONLY valid JSON with keys: topic, consensus, dissent, gaps (list), tags (list)."""


def run_council() -> list[dict]:
    """
    Process all dispatches above 0.65 SIL that haven't generated a council session.
    Returns list of new session dicts.
    """
    db  = get_db()
    gw  = get_gateway()

    # Find qualifying dispatches
    dispatches = db.get_dispatches(limit=200)
    qualifying = [
        d for d in dispatches
        if d.get("sil_score", 0) >= COUNCIL_THRESHOLD
        and d.get("type") == "dispatch"
    ]

    sessions_produced = []

    for dispatch in qualifying[:3]:   # cap per run to respect token budget
        dispatch_id = dispatch.get("id")

        # Skip if already has a council session
        existing = db.get_recent_sessions(limit=100)
        already  = any(s.get("source_dispatch_id") == dispatch_id for s in existing)
        if already:
            continue

        session = _debate(dispatch, gw)
        if session:
            session["source_dispatch_id"] = dispatch_id
            session_id = db.save_council_session(session)
            session["id"] = session_id
            sessions_produced.append(session)
            logger.info("Council session %s produced for dispatch %s",
                        session_id, dispatch_id)

    return sessions_produced


def _debate(dispatch: dict, gw) -> dict | None:
    body    = dispatch.get("body", "")
    agent   = dispatch.get("agent", "")
    context = f"[DISPATCH from {agent}]\n{body[:1500]}"

    logos_text = gw.call(
        agent      = "COUNCIL",
        system     = LOGOS_SYSTEM,
        user       = f"Analyse this dispatch:\n\n{context}",
        max_tokens = 300,
        temperature= 0.6,
    )
    if not logos_text:
        return None

    krisis_text = gw.call(
        agent      = "COUNCIL",
        system     = KRISIS_SYSTEM,
        user       = (f"Dispatch:\n{context}\n\n"
                      f"LOGOS claims:\n{logos_text}\n\n"
                      "Stress-test these claims."),
        max_tokens = 300,
        temperature= 0.6,
    )
    if not krisis_text:
        return None

    lacuna_text = gw.call(
        agent      = "COUNCIL",
        system     = LACUNA_SYSTEM,
        user       = (f"Dispatch:\n{context}\n\n"
                      f"LOGOS:\n{logos_text}\n\n"
                      f"KRISIS:\n{krisis_text}\n\n"
                      "What is missing from this analysis?"),
        max_tokens = 300,
        temperature= 0.6,
    )
    if not lacuna_text:
        return None

    synthesis_prompt = (
        f"Dispatch (agent={agent}):\n{context}\n\n"
        f"LOGOS:\n{logos_text}\n\n"
        f"KRISIS:\n{krisis_text}\n\n"
        f"LACUNA:\n{lacuna_text}\n\n"
        "Produce JSON with keys: topic (str), consensus (str), dissent (str), "
        "gaps (list of str, max 3), tags (list of str, max 5). "
        "Return ONLY valid JSON. No preamble, no backticks."
    )

    synth_raw = gw.call(
        agent      = "COUNCIL",
        system     = SYNTHESIS_SYSTEM,
        user       = synthesis_prompt,
        max_tokens = 500,
        temperature= 0.4,
    )

    structured: dict = {}
    if synth_raw:
        try:
            clean = synth_raw.strip().lstrip("```json").rstrip("```").strip()
            structured = json.loads(clean)
        except Exception as e:
            logger.warning("Council synthesis JSON parse failed: %s", e)
            structured = {"topic": body[:80], "consensus": synth_raw[:300]}

    exchanges = [
        {"voice": "LOGOS",  "text": logos_text},
        {"voice": "KRISIS", "text": krisis_text},
        {"voice": "LACUNA", "text": lacuna_text},
    ]

    return {
        "topic":     structured.get("topic", body[:80]),
        "exchanges": exchanges,
        "consensus": structured.get("consensus", ""),
        "dissent":   structured.get("dissent", ""),
        "gaps":      structured.get("gaps", []),
        "tags":      structured.get("tags", []),
        "processed": False,
    }
