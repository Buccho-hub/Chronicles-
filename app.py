"""
app.py
The Chronicles -- Flask application.
Scheduler, convergence/divergence detection, REST API.
"""

import os
import re
import json
import logging
from datetime import datetime, timezone

from flask import Flask, jsonify, request, send_from_directory
from apscheduler.schedulers.background import BackgroundScheduler

from database import get_db
from agents import ALL_AGENTS, AGENT_MAP
from agents.council import run_council
from agents.oracle  import run_oracle

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

app = Flask(__name__, static_folder=".", static_url_path="")

# -- Convergence / Divergence config ------------------------------------------

TERRITORY_GROUPS = {
    "economic":    {"SOLOMON",        "AMOS"},
    "geopolitical":{"DANIEL",         "MARCUS_AURELIUS"},
    "social":      {"RUTH",           "HILDEGARD"},
    "systemic":    {"JOHN",           "AUGUSTINE"},
}

DIVERGENT_PAIRS = [
    ("SOLOMON",        "AMOS"),
    ("DANIEL",         "JOHN"),
    ("MARCUS_AURELIUS","AUGUSTINE"),
    ("RUTH",           "AMOS"),
]

HIGH_SIGNAL_KEYWORDS = [
    "collapse", "crisis", "unprecedented", "record", "systemic",
    "inequality", "surveillance", "empire", "transition", "power",
    "ecological", "extraction", "concentration", "control",
]

# Patterns that indicate an item is an image/media description rather than news
IMAGE_NOISE_PATTERNS = [
    r"the image (presented|shows|reveals|depicts)",
    r"(canoe|rainbow|palm tree|wind turbine|photograph|photo)",
    r"juxtaposition of the natural",
    r"image presented reveals",
]


def _agent_territory(agent_name: str) -> str | None:
    for territory, members in TERRITORY_GROUPS.items():
        if agent_name.upper() in members:
            return territory
    return None


def _is_image_dispatch(body: str) -> bool:
    """Return True if this dispatch is describing an image rather than a news signal."""
    lower = body.lower()
    return any(re.search(p, lower) for p in IMAGE_NOISE_PATTERNS)


def detect_convergence(new_dispatches: list[dict]) -> list[dict]:
    db          = get_db()
    recent      = db.get_dispatches(limit=200)
    all_relevant= recent + new_dispatches

    cluster_agents: dict[str, dict[str, list]] = {}
    for dispatch in all_relevant:
        if dispatch.get("type") != "dispatch":
            continue
        body      = (dispatch.get("body", "") + " " + dispatch.get("headline", "")).lower()
        agent     = dispatch.get("agent", "")
        territory = _agent_territory(agent)
        if not territory:
            continue
        for kw in HIGH_SIGNAL_KEYWORDS:
            if kw in body:
                if kw not in cluster_agents:
                    cluster_agents[kw] = {}
                if territory not in cluster_agents[kw]:
                    cluster_agents[kw][territory] = []
                if agent not in cluster_agents[kw][territory]:
                    cluster_agents[kw][territory].append(agent)

    alerts = []
    for kw, territory_map in cluster_agents.items():
        independent_territories = [t for t, agents in territory_map.items() if agents]
        if len(independent_territories) >= 3:
            contributing_agents = []
            for agents in territory_map.values():
                contributing_agents.extend(agents)

            qualifying = [
                d for d in all_relevant
                if d.get("agent", "") in contributing_agents
                and len(d.get("body", "")) >= 120
                and kw in (d.get("body", "") + d.get("headline", "")).lower()
            ]
            if len(set(d["agent"] for d in qualifying)) < 3:
                continue

            # Dedup: check headline keyword match
            existing = db.get_dispatches(limit=100, type_filter="convergence_alert")
            already  = any(
                kw.upper() in (e.get("headline", "") or "").upper()
                for e in existing
            )
            if already:
                continue

            body_text = (
                f"CONVERGENCE SIGNAL: '{kw}' flagged independently by agents from "
                f"{len(independent_territories)} different analytical domains: "
                f"{', '.join(independent_territories)}.\n\n"
                f"Contributing agents: {', '.join(set(d['agent'] for d in qualifying))}.\n\n"
                f"When {len(independent_territories)} distinct civilisational frameworks "
                f"converge on the same phenomenon independently, the signal exceeds any "
                f"single analytical lens."
            )
            alert = {
                "type":     "convergence_alert",
                "agent":    "SYSTEM",
                "body":     body_text,
                "headline": f"CONVERGENCE: {kw.upper()} -- {len(independent_territories)} independent domains",
                "tags":     [kw, "convergence"],
                "mentions": list(set(d["agent"] for d in qualifying)),
                "sil_score": 0.80,
            }
            alerts.append(alert)

    return alerts


def detect_divergence(new_dispatches: list[dict]) -> list[dict]:
    db     = get_db()
    recent = db.get_dispatches(limit=100) + new_dispatches
    debates = []

    # Load existing debates once
    existing_debates = db.get_dispatches(limit=100, type_filter="debate")

    for agent_a, agent_b in DIVERGENT_PAIRS:
        # Dedup: one debate per pair total (keyed by agent string)
        pair_agent_str = f"{agent_a}:{agent_b}"
        already = any(
            e.get("agent", "") == pair_agent_str
            for e in existing_debates
        )
        if already:
            continue

        a_dispatches = [
            d for d in recent
            if d.get("agent") == agent_a
            and d.get("type") == "dispatch"
            and not _is_image_dispatch(d.get("body", ""))
        ]
        b_dispatches = [
            d for d in recent
            if d.get("agent") == agent_b
            and d.get("type") == "dispatch"
            and not _is_image_dispatch(d.get("body", ""))
        ]
        if not a_dispatches or not b_dispatches:
            continue

        # Use only the best-scored dispatch from each agent (first = highest SIL)
        da   = a_dispatches[0]
        db_d = b_dispatches[0]

        a_tags = set(da.get("tags", []))
        b_tags = set(db_d.get("tags", []))
        shared = a_tags & b_tags
        topic  = ", ".join(list(shared)[:3]) if shared else "civilisational systems"

        a_body = da.get("body", "")[:500].strip()
        b_body = db_d.get("body", "")[:500].strip()

        body_text = (
            f"{agent_a}:\n{a_body}\n\n"
            f"{agent_b.replace('_AURELIUS', ' AURELIUS')}:\n{b_body}\n\n"
            f"Two minds, same data, different conclusions. "
            f"The disagreement is not error -- it is the full complexity of the problem."
        )
        debate = {
            "type":     "debate",
            "agent":    pair_agent_str,
            "body":     body_text,
            "headline": f"DIVERGENCE: {agent_a} vs {agent_b.replace('_AURELIUS',' AURELIUS')} -- {topic}",
            "tags":     list(shared) if shared else ["power"],
            "mentions": [agent_a, agent_b],
        }
        debates.append(debate)

    return debates


# -- Agent run helpers ---------------------------------------------------------

def run_agent(agent_name: str):
    agent = AGENT_MAP.get(agent_name.upper())
    if not agent:
        logger.warning("Unknown agent: %s", agent_name)
        return
    try:
        dispatches = agent.run()
        if dispatches:
            db = get_db()
            alerts = detect_convergence(dispatches)
            debates = detect_divergence(dispatches)
            for a in alerts:
                db.save_dispatch(a)
            for d in debates:
                db.save_dispatch(d)
    except Exception as exc:
        logger.error("Agent %s run failed: %s", agent_name, exc)


def run_council_job():
    try:
        run_council()
    except Exception as exc:
        logger.error("Council job failed: %s", exc)


def run_oracle_job():
    try:
        run_oracle()
    except Exception as exc:
        logger.error("Oracle job failed: %s", exc)


# -- Scheduler -----------------------------------------------------------------

def start_scheduler():
    sched = BackgroundScheduler(timezone="UTC")
    sched.add_job(lambda: run_agent("SOLOMON"),         "interval", hours=3,  id="solomon",   jitter=60)
    sched.add_job(lambda: run_agent("DANIEL"),          "interval", hours=2,  id="daniel",    jitter=60)
    sched.add_job(lambda: run_agent("AMOS"),            "interval", hours=3,  id="amos",      minutes=90, jitter=60)
    sched.add_job(lambda: run_agent("RUTH"),            "interval", hours=4,  id="ruth",      jitter=60)
    sched.add_job(lambda: run_agent("JOHN"),            "interval", hours=3,  id="john",      jitter=60)
    sched.add_job(lambda: run_agent("AUGUSTINE"),       "interval", hours=4,  id="augustine", minutes=120, jitter=60)
    sched.add_job(lambda: run_agent("MARCUS_AURELIUS"), "interval", hours=3,  id="marcus",    minutes=90, jitter=60)
    sched.add_job(lambda: run_agent("HILDEGARD"),       "interval", hours=6,  id="hildegard", jitter=60)
    sched.add_job(run_council_job,                      "interval", hours=4,  id="council",   jitter=60)
    sched.add_job(run_oracle_job,                       "interval", hours=4,  id="oracle",    minutes=60, jitter=60)
    sched.start()
    logger.info("Scheduler started")
    return sched


# -- Routes --------------------------------------------------------------------

@app.route("/")
def index():
    return send_from_directory(".", "index.html")

@app.route("/style.css")
def stylesheet():
    return send_from_directory(".", "style.css")

@app.route("/api/dispatches")
def api_dispatches():
    db           = get_db()
    limit        = min(int(request.args.get("limit", 50)), 200)
    type_filter  = request.args.get("type")
    agent_filter = request.args.get("agent")
    dispatches   = db.get_dispatches(limit=limit, type_filter=type_filter,
                                     agent_filter=agent_filter)
    return jsonify(dispatches)

@app.route("/api/briefs")
def api_briefs():
    db    = get_db()
    limit = min(int(request.args.get("limit", 20)), 50)
    return jsonify(db.get_briefs(limit=limit))

@app.route("/api/stats")
def api_stats():
    return jsonify(get_db().get_weekly_stats())

@app.route("/api/agents")
def api_agents():
    return jsonify([
        {"name": a.name, "era": a.era, "color": a.color, "territory": a.territory}
        for a in ALL_AGENTS
    ])

@app.route("/api/budget")
def api_budget():
    from agents.llm_gateway import get_gateway
    return jsonify(get_gateway().budget_status())

@app.route("/api/trigger/<agent_name>", methods=["GET", "POST"])
def api_trigger(agent_name: str):
    if agent_name.upper() == "COUNCIL":
        run_council_job()
    elif agent_name.upper() == "ORACLE":
        run_oracle_job()
    else:
        run_agent(agent_name)
    return jsonify({"triggered": agent_name.upper()})

@app.route("/api/sessions")
def api_sessions():
    return jsonify(get_db().get_recent_sessions(limit=20))


# -- Entry point ---------------------------------------------------------------

if __name__ == "__main__":
    start_scheduler()
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)
else:
    start_scheduler()
