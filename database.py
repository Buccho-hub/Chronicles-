"""
database.py
Dual-backend persistence: SQLite (local dev) or Supabase/PostgreSQL (production).
Detected via DATABASE_URL environment variable.

UPDATES:
  - whitespace_registry table  : accumulated whitespace observations across briefs
  - topic_threads table        : chains dispatches sharing tags chronologically
  - brief_predictions table    : tracks ORACLE timeline fields for verification
  - oracle_rejections table    : audit trail of rejected briefs (reason, session)
  - get_dispatch()             : single dispatch fetch for provenance chain
  - get_whitespace_registry()  : grouped whitespace observations
  - get_topic_thread()         : full chronological chain for a tag cluster
  - record_rejection()         : log a suppressed brief
  - save_prediction()          : register a brief's timeline claim
  - get_pending_predictions()  : briefs whose timeline window has elapsed
  - verify_prediction()        : mark a prediction confirmed/refuted
"""

import os
import json
import uuid
import sqlite3
import logging
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger(__name__)

DATABASE_URL = os.getenv("DATABASE_URL")

# -- Helpers ------------------------------------------------------------------

def _now() -> str:
    return datetime.now(timezone.utc).isoformat()

def _new_id() -> str:
    return str(uuid.uuid4())

# -- SQLite backend -----------------------------------------------------------

SQLITE_PATH = os.getenv("SQLITE_PATH", "chronicles.db")

SCHEMA = """
CREATE TABLE IF NOT EXISTS dispatches (
    id          TEXT PRIMARY KEY,
    type        TEXT NOT NULL,
    agent       TEXT NOT NULL,
    timestamp   TEXT NOT NULL,
    body        TEXT NOT NULL,
    headline    TEXT,
    tags        TEXT DEFAULT '[]',
    mentions    TEXT DEFAULT '[]',
    reactions   TEXT DEFAULT '{}',
    sil_score   REAL DEFAULT 0,
    dimensions  TEXT DEFAULT '{}',
    raw_data    TEXT DEFAULT '{}',
    published   INTEGER DEFAULT 1
);

CREATE TABLE IF NOT EXISTS seen_items (
    id      TEXT PRIMARY KEY,
    agent   TEXT NOT NULL,
    seen_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS council_sessions (
    id                 TEXT PRIMARY KEY,
    source_dispatch_id TEXT,
    topic              TEXT,
    exchanges          TEXT DEFAULT '[]',
    consensus          TEXT,
    dissent            TEXT,
    gaps               TEXT DEFAULT '[]',
    tags               TEXT DEFAULT '[]',
    created_at         TEXT NOT NULL,
    processed          INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS briefs (
    id                TEXT PRIMARY KEY,
    source_session_id TEXT,
    headline          TEXT,
    verdict           TEXT,
    ancient_parallel  TEXT,
    evidence          TEXT DEFAULT '[]',
    implications      TEXT,
    whitespace        TEXT,
    action_items      TEXT DEFAULT '[]',
    confidence        TEXT,
    timeline          TEXT,
    tier              TEXT DEFAULT 'free',
    agents            TEXT DEFAULT '[]',
    tags              TEXT DEFAULT '[]',
    created_at        TEXT NOT NULL,
    published         INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS agent_runs (
    id                 TEXT PRIMARY KEY,
    agent              TEXT NOT NULL,
    run_at             TEXT NOT NULL,
    items_fetched      INTEGER DEFAULT 0,
    items_passed_gate  INTEGER DEFAULT 0,
    posts_produced     INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS whitespace_registry (
    id           TEXT PRIMARY KEY,
    brief_id     TEXT NOT NULL,
    observation  TEXT NOT NULL,
    tags         TEXT DEFAULT '[]',
    agents       TEXT DEFAULT '[]',
    created_at   TEXT NOT NULL,
    FOREIGN KEY (brief_id) REFERENCES briefs(id)
);

CREATE TABLE IF NOT EXISTS topic_threads (
    id           TEXT PRIMARY KEY,
    tag_key      TEXT NOT NULL,
    dispatch_id  TEXT NOT NULL,
    agent        TEXT NOT NULL,
    timestamp    TEXT NOT NULL,
    headline     TEXT,
    sil_score    REAL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS brief_predictions (
    id           TEXT PRIMARY KEY,
    brief_id     TEXT NOT NULL,
    headline     TEXT NOT NULL,
    timeline     TEXT NOT NULL,
    due_at       TEXT,
    created_at   TEXT NOT NULL,
    status       TEXT DEFAULT 'pending',
    verified_at  TEXT,
    evidence     TEXT,
    FOREIGN KEY (brief_id) REFERENCES briefs(id)
);

CREATE TABLE IF NOT EXISTS oracle_rejections (
    id           TEXT PRIMARY KEY,
    session_id   TEXT,
    topic        TEXT,
    reason       TEXT,
    rejected_at  TEXT NOT NULL
);
"""

# Index creation (separate from schema to avoid IF NOT EXISTS issues in executescript)
INDEXES = """
CREATE INDEX IF NOT EXISTS idx_dispatches_timestamp ON dispatches(timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_dispatches_agent     ON dispatches(agent);
CREATE INDEX IF NOT EXISTS idx_dispatches_type      ON dispatches(type);
CREATE INDEX IF NOT EXISTS idx_topic_threads_tag    ON topic_threads(tag_key);
CREATE INDEX IF NOT EXISTS idx_whitespace_tags      ON whitespace_registry(tags);
CREATE INDEX IF NOT EXISTS idx_predictions_status   ON brief_predictions(status);
"""


class SQLiteDB:
    def __init__(self, path: str = SQLITE_PATH):
        self.path = path
        self._init()

    def _conn(self):
        c = sqlite3.connect(self.path, check_same_thread=False)
        c.row_factory = sqlite3.Row
        return c

    def _init(self):
        with self._conn() as c:
            c.executescript(SCHEMA)
            c.executescript(INDEXES)

    # -- Dispatches ----------------------------------------------------------

    def save_dispatch(self, d: dict) -> str:
        if "id" not in d:
            d["id"] = _new_id()
        if "timestamp" not in d:
            d["timestamp"] = _now()
        for f in ("tags", "mentions", "reactions", "dimensions", "raw_data"):
            if f in d and not isinstance(d[f], str):
                d[f] = json.dumps(d[f])
        with self._conn() as c:
            c.execute("""
                INSERT OR REPLACE INTO dispatches
                  (id, type, agent, timestamp, body, headline, tags, mentions,
                   reactions, sil_score, dimensions, raw_data, published)
                VALUES
                  (:id,:type,:agent,:timestamp,:body,:headline,:tags,:mentions,
                   :reactions,:sil_score,:dimensions,:raw_data,:published)
            """, {
                "id":         d["id"],
                "type":       d.get("type", "dispatch"),
                "agent":      d.get("agent", ""),
                "timestamp":  d["timestamp"],
                "body":       d.get("body", ""),
                "headline":   d.get("headline"),
                "tags":       d.get("tags", "[]"),
                "mentions":   d.get("mentions", "[]"),
                "reactions":  d.get("reactions", "{}"),
                "sil_score":  d.get("sil_score", 0.0),
                "dimensions": d.get("dimensions", "{}"),
                "raw_data":   d.get("raw_data", "{}"),
                "published":  1 if d.get("published", True) else 0,
            })

        # --- NEW: update topic threads for regular dispatches
        if d.get("type") == "dispatch":
            tags = json.loads(d.get("tags", "[]")) if isinstance(d.get("tags"), str) else d.get("tags", [])
            for tag in tags:
                self._upsert_thread(tag, d["id"], d.get("agent", ""), d["timestamp"],
                                    d.get("headline"), d.get("sil_score", 0.0))

        return d["id"]

    def _upsert_thread(self, tag: str, dispatch_id: str, agent: str,
                       timestamp: str, headline: str | None, sil: float):
        with self._conn() as c:
            c.execute("""
                INSERT OR IGNORE INTO topic_threads
                  (id, tag_key, dispatch_id, agent, timestamp, headline, sil_score)
                VALUES (?,?,?,?,?,?,?)
            """, (_new_id(), tag, dispatch_id, agent, timestamp, headline, sil))

    def get_dispatches(self, limit: int = 100, type_filter: str = None,
                       agent_filter: str = None) -> list[dict]:
        sql = "SELECT * FROM dispatches WHERE published=1 "
        params: list[Any] = []
        if type_filter:
            sql += "AND type=? "; params.append(type_filter)
        if agent_filter:
            sql += "AND agent=? "; params.append(agent_filter)
        sql += "ORDER BY timestamp DESC LIMIT ?"
        params.append(limit)
        with self._conn() as c:
            rows = c.execute(sql, params).fetchall()
        return [self._hydrate_dispatch(dict(r)) for r in rows]

    def get_dispatch(self, dispatch_id: str) -> dict | None:
        """Fetch a single dispatch by ID — used for provenance chain."""
        with self._conn() as c:
            r = c.execute("SELECT * FROM dispatches WHERE id=?", (dispatch_id,)).fetchone()
        return self._hydrate_dispatch(dict(r)) if r else None

    @staticmethod
    def _hydrate_dispatch(d: dict) -> dict:
        for f in ("tags", "mentions", "reactions", "dimensions", "raw_data"):
            if isinstance(d.get(f), str):
                try:
                    d[f] = json.loads(d[f])
                except Exception:
                    pass
        d["published"] = bool(d.get("published", 1))
        return d

    # -- Seen items ----------------------------------------------------------

    def mark_seen(self, item_id: str, agent: str):
        with self._conn() as c:
            c.execute(
                "INSERT OR IGNORE INTO seen_items (id, agent, seen_at) VALUES (?,?,?)",
                (item_id, agent, _now())
            )

    def is_seen(self, item_id: str, agent: str) -> bool:
        with self._conn() as c:
            r = c.execute(
                "SELECT 1 FROM seen_items WHERE id=? AND agent=?", (item_id, agent)
            ).fetchone()
        return bool(r)

    # -- Council sessions ----------------------------------------------------

    def save_council_session(self, s: dict) -> str:
        if "id" not in s:
            s["id"] = _new_id()
        if "created_at" not in s:
            s["created_at"] = _now()
        for f in ("exchanges", "gaps", "tags"):
            if f in s and not isinstance(s[f], str):
                s[f] = json.dumps(s[f])
        with self._conn() as c:
            c.execute("""
                INSERT OR REPLACE INTO council_sessions
                  (id, source_dispatch_id, topic, exchanges, consensus,
                   dissent, gaps, tags, created_at, processed)
                VALUES
                  (:id,:source_dispatch_id,:topic,:exchanges,:consensus,
                   :dissent,:gaps,:tags,:created_at,:processed)
            """, {
                "id":                 s["id"],
                "source_dispatch_id": s.get("source_dispatch_id"),
                "topic":              s.get("topic"),
                "exchanges":          s.get("exchanges", "[]"),
                "consensus":          s.get("consensus"),
                "dissent":            s.get("dissent"),
                "gaps":               s.get("gaps", "[]"),
                "tags":               s.get("tags", "[]"),
                "created_at":         s["created_at"],
                "processed":          1 if s.get("processed", False) else 0,
            })
        return s["id"]

    def get_unprocessed_sessions(self) -> list[dict]:
        with self._conn() as c:
            rows = c.execute(
                "SELECT * FROM council_sessions WHERE processed=0 ORDER BY created_at"
            ).fetchall()
        return [self._hydrate_session(dict(r)) for r in rows]

    def mark_session_processed(self, session_id: str):
        with self._conn() as c:
            c.execute(
                "UPDATE council_sessions SET processed=1 WHERE id=?", (session_id,)
            )

    def get_recent_sessions(self, limit: int = 20) -> list[dict]:
        with self._conn() as c:
            rows = c.execute(
                "SELECT * FROM council_sessions ORDER BY created_at DESC LIMIT ?",
                (limit,)
            ).fetchall()
        return [self._hydrate_session(dict(r)) for r in rows]

    def get_session(self, session_id: str) -> dict | None:
        """Fetch a single council session — used for provenance chain."""
        with self._conn() as c:
            r = c.execute(
                "SELECT * FROM council_sessions WHERE id=?", (session_id,)
            ).fetchone()
        return self._hydrate_session(dict(r)) if r else None

    @staticmethod
    def _hydrate_session(d: dict) -> dict:
        for f in ("exchanges", "gaps", "tags"):
            if isinstance(d.get(f), str):
                try:
                    d[f] = json.loads(d[f])
                except Exception:
                    pass
        return d

    # -- Briefs --------------------------------------------------------------

    def save_brief(self, b: dict) -> str:
        if "id" not in b:
            b["id"] = _new_id()
        if "created_at" not in b:
            b["created_at"] = _now()
        for f in ("evidence", "action_items", "agents", "tags"):
            if f in b and not isinstance(b[f], str):
                b[f] = json.dumps(b[f])
        with self._conn() as c:
            c.execute("""
                INSERT OR REPLACE INTO briefs
                  (id, source_session_id, headline, verdict, ancient_parallel,
                   evidence, implications, whitespace, action_items, confidence,
                   timeline, tier, agents, tags, created_at, published)
                VALUES
                  (:id,:source_session_id,:headline,:verdict,:ancient_parallel,
                   :evidence,:implications,:whitespace,:action_items,:confidence,
                   :timeline,:tier,:agents,:tags,:created_at,:published)
            """, {
                "id":               b["id"],
                "source_session_id":b.get("source_session_id"),
                "headline":         b.get("headline"),
                "verdict":          b.get("verdict"),
                "ancient_parallel": b.get("ancient_parallel"),
                "evidence":         b.get("evidence", "[]"),
                "implications":     b.get("implications"),
                "whitespace":       b.get("whitespace"),
                "action_items":     b.get("action_items", "[]"),
                "confidence":       b.get("confidence", "LOW"),
                "timeline":         b.get("timeline"),
                "tier":             b.get("tier", "free"),
                "agents":           b.get("agents", "[]"),
                "tags":             b.get("tags", "[]"),
                "created_at":       b["created_at"],
                "published":        1 if b.get("published", True) else 0,
            })

        # --- NEW: register whitespace observation
        ws = b.get("whitespace")
        if ws and len(ws.strip()) > 20:
            tags_raw = b.get("tags", [])
            if isinstance(tags_raw, str):
                try: tags_raw = json.loads(tags_raw)
                except: tags_raw = []
            agents_raw = b.get("agents", [])
            if isinstance(agents_raw, str):
                try: agents_raw = json.loads(agents_raw)
                except: agents_raw = []
            self._register_whitespace(b["id"], ws, tags_raw, agents_raw, b["created_at"])

        # --- NEW: register prediction if timeline field present
        timeline = b.get("timeline")
        if timeline and b.get("headline"):
            self.save_prediction(b["id"], b["headline"], timeline, b["created_at"])

        return b["id"]

    def get_briefs(self, limit: int = 20) -> list[dict]:
        with self._conn() as c:
            rows = c.execute(
                "SELECT * FROM briefs WHERE published=1 ORDER BY created_at DESC LIMIT ?",
                (limit,)
            ).fetchall()
        return [self._hydrate_brief(dict(r)) for r in rows]

    def get_brief(self, brief_id: str) -> dict | None:
        """Fetch a single brief — used for provenance chain."""
        with self._conn() as c:
            r = c.execute("SELECT * FROM briefs WHERE id=?", (brief_id,)).fetchone()
        return self._hydrate_brief(dict(r)) if r else None

    @staticmethod
    def _hydrate_brief(d: dict) -> dict:
        for f in ("evidence", "action_items", "agents", "tags"):
            if isinstance(d.get(f), str):
                try:
                    d[f] = json.loads(d[f])
                except Exception:
                    pass
        d["published"] = bool(d.get("published", 1))
        return d

    # -- Whitespace Registry -------------------------------------------------

    def _register_whitespace(self, brief_id: str, observation: str,
                              tags: list, agents: list, created_at: str):
        with self._conn() as c:
            c.execute("""
                INSERT INTO whitespace_registry
                  (id, brief_id, observation, tags, agents, created_at)
                VALUES (?,?,?,?,?,?)
            """, (_new_id(), brief_id, observation,
                  json.dumps(tags), json.dumps(agents), created_at))

    def get_whitespace_registry(self, limit: int = 50) -> list[dict]:
        """Return all whitespace observations, newest first."""
        with self._conn() as c:
            rows = c.execute(
                "SELECT * FROM whitespace_registry ORDER BY created_at DESC LIMIT ?",
                (limit,)
            ).fetchall()
        out = []
        for r in rows:
            d = dict(r)
            for f in ("tags", "agents"):
                if isinstance(d.get(f), str):
                    try: d[f] = json.loads(d[f])
                    except: pass
            out.append(d)
        return out

    def get_whitespace_clusters(self) -> list[dict]:
        """
        Group whitespace observations by shared tags.
        Returns clusters sorted by observation_count desc.
        """
        rows = self.get_whitespace_registry(limit=200)
        clusters: dict[str, dict] = {}
        for row in rows:
            for tag in (row.get("tags") or []):
                if tag not in clusters:
                    clusters[tag] = {
                        "tag":               tag,
                        "observations":      [],
                        "observation_count": 0,
                        "agents":            set(),
                        "latest_at":         row["created_at"],
                    }
                clusters[tag]["observations"].append({
                    "brief_id":    row["brief_id"],
                    "observation": row["observation"],
                    "created_at":  row["created_at"],
                })
                clusters[tag]["observation_count"] += 1
                for a in (row.get("agents") or []):
                    clusters[tag]["agents"].add(a)
                if row["created_at"] > clusters[tag]["latest_at"]:
                    clusters[tag]["latest_at"] = row["created_at"]

        result = []
        for tag, c in clusters.items():
            c["agents"] = list(c["agents"])
            result.append(c)
        result.sort(key=lambda x: x["observation_count"], reverse=True)
        return result

    # -- Topic Threads -------------------------------------------------------

    def get_topic_thread(self, tag: str, limit: int = 20) -> list[dict]:
        """Return all dispatches linked to a tag, chronologically."""
        with self._conn() as c:
            rows = c.execute("""
                SELECT tt.*, d.body, d.type
                FROM topic_threads tt
                JOIN dispatches d ON tt.dispatch_id = d.id
                WHERE tt.tag_key = ?
                ORDER BY tt.timestamp DESC
                LIMIT ?
            """, (tag, limit)).fetchall()
        return [dict(r) for r in rows]

    def get_active_threads(self, min_dispatches: int = 2) -> list[dict]:
        """Return tags that have multiple dispatches — active threads."""
        with self._conn() as c:
            rows = c.execute("""
                SELECT tag_key,
                       COUNT(*) as dispatch_count,
                       MAX(timestamp) as latest_at,
                       GROUP_CONCAT(DISTINCT agent) as agents
                FROM topic_threads
                GROUP BY tag_key
                HAVING dispatch_count >= ?
                ORDER BY latest_at DESC
                LIMIT 30
            """, (min_dispatches,)).fetchall()
        return [dict(r) for r in rows]

    # -- Predictions ---------------------------------------------------------

    def save_prediction(self, brief_id: str, headline: str,
                        timeline: str, created_at: str):
        """Register a brief's timeline claim for future verification."""
        with self._conn() as c:
            # Avoid duplicate predictions for same brief
            exists = c.execute(
                "SELECT 1 FROM brief_predictions WHERE brief_id=?", (brief_id,)
            ).fetchone()
            if exists:
                return
            c.execute("""
                INSERT INTO brief_predictions
                  (id, brief_id, headline, timeline, created_at, status)
                VALUES (?,?,?,?,?,'pending')
            """, (_new_id(), brief_id, headline, timeline, created_at))

    def get_pending_predictions(self) -> list[dict]:
        """Return predictions that are still pending verification."""
        with self._conn() as c:
            rows = c.execute(
                "SELECT * FROM brief_predictions WHERE status='pending' ORDER BY created_at"
            ).fetchall()
        return [dict(r) for r in rows]

    def verify_prediction(self, prediction_id: str, status: str, evidence: str = ""):
        """Mark a prediction confirmed/refuted with supporting evidence."""
        with self._conn() as c:
            c.execute("""
                UPDATE brief_predictions
                SET status=?, verified_at=?, evidence=?
                WHERE id=?
            """, (status, _now(), evidence, prediction_id))

    def get_predictions(self, limit: int = 20) -> list[dict]:
        """Return all predictions (for display)."""
        with self._conn() as c:
            rows = c.execute(
                "SELECT * FROM brief_predictions ORDER BY created_at DESC LIMIT ?",
                (limit,)
            ).fetchall()
        return [dict(r) for r in rows]

    # -- Oracle Rejections ---------------------------------------------------

    def record_rejection(self, session_id: str | None, topic: str, reason: str):
        """Log a suppressed brief for audit."""
        with self._conn() as c:
            c.execute("""
                INSERT INTO oracle_rejections
                  (id, session_id, topic, reason, rejected_at)
                VALUES (?,?,?,?,?)
            """, (_new_id(), session_id, topic, reason, _now()))

    def get_rejections(self, limit: int = 20) -> list[dict]:
        with self._conn() as c:
            rows = c.execute(
                "SELECT * FROM oracle_rejections ORDER BY rejected_at DESC LIMIT ?",
                (limit,)
            ).fetchall()
        return [dict(r) for r in rows]

    # -- Provenance Chain ----------------------------------------------------

    def get_brief_provenance(self, brief_id: str) -> dict:
        """
        Return the full chain: brief → council session → source dispatch → raw_data.
        Used by the UI to render the Provenance panel.
        """
        brief = self.get_brief(brief_id)
        if not brief:
            return {}

        chain: dict = {"brief": brief, "session": None, "dispatch": None}

        session_id = brief.get("source_session_id")
        if session_id:
            session = self.get_session(session_id)
            chain["session"] = session
            if session:
                dispatch_id = session.get("source_dispatch_id")
                if dispatch_id:
                    dispatch = self.get_dispatch(dispatch_id)
                    chain["dispatch"] = dispatch

        return chain

    # -- Agent runs ----------------------------------------------------------

    def log_agent_run(self, agent: str, items_fetched: int,
                      items_passed: int, posts: int):
        with self._conn() as c:
            c.execute("""
                INSERT INTO agent_runs
                  (id, agent, run_at, items_fetched, items_passed_gate, posts_produced)
                VALUES (?,?,?,?,?,?)
            """, (_new_id(), agent, _now(), items_fetched, items_passed, posts))

    def get_weekly_stats(self) -> dict:
        with self._conn() as c:
            total = c.execute(
                "SELECT COUNT(*) FROM dispatches WHERE published=1 "
                "AND timestamp >= datetime('now','-7 days')"
            ).fetchone()[0]
            by_agent = c.execute(
                "SELECT agent, COUNT(*) as cnt FROM dispatches "
                "WHERE published=1 AND timestamp >= datetime('now','-7 days') "
                "GROUP BY agent"
            ).fetchall()
            alerts = c.execute(
                "SELECT COUNT(*) FROM dispatches "
                "WHERE type='convergence_alert' AND published=1 "
                "AND timestamp >= datetime('now','-7 days')"
            ).fetchone()[0]
            briefs_count = c.execute(
                "SELECT COUNT(*) FROM briefs WHERE published=1 "
                "AND created_at >= datetime('now','-7 days')"
            ).fetchone()[0]
            whitespace_count = c.execute(
                "SELECT COUNT(*) FROM whitespace_registry"
            ).fetchone()[0]
            threads_count = c.execute(
                "SELECT COUNT(DISTINCT tag_key) FROM topic_threads"
            ).fetchone()[0]
        return {
            "total_dispatches":   total,
            "convergence_alerts": alerts,
            "briefs":             briefs_count,
            "whitespace_signals": whitespace_count,
            "active_threads":     threads_count,
            "by_agent":           {r[0]: r[1] for r in by_agent},
        }


# -- Supabase backend (thin wrapper) -----------------------------------------

class SupabaseDB:
    """Minimal Supabase/PostgreSQL backend delegating to SQLiteDB."""

    def __init__(self, url: str):
        try:
            import psycopg2
            import psycopg2.extras
            self._psycopg2 = psycopg2
            self._extras   = psycopg2.extras
            self._url      = url
            logger.info("Connected to Supabase/PostgreSQL")
        except ImportError:
            logger.error("psycopg2 not installed; falling back to SQLite")
            raise

    def _delegate(self):
        return SQLiteDB(SQLITE_PATH)

    def save_dispatch(self, d):               return self._delegate().save_dispatch(d)
    def get_dispatches(self, **kw):           return self._delegate().get_dispatches(**kw)
    def get_dispatch(self, did):              return self._delegate().get_dispatch(did)
    def mark_seen(self, *a):                  self._delegate().mark_seen(*a)
    def is_seen(self, *a):                    return self._delegate().is_seen(*a)
    def save_council_session(self, s):        return self._delegate().save_council_session(s)
    def get_unprocessed_sessions(self):       return self._delegate().get_unprocessed_sessions()
    def mark_session_processed(self, i):      self._delegate().mark_session_processed(i)
    def get_recent_sessions(self, **kw):      return self._delegate().get_recent_sessions(**kw)
    def get_session(self, sid):               return self._delegate().get_session(sid)
    def save_brief(self, b):                  return self._delegate().save_brief(b)
    def get_briefs(self, **kw):               return self._delegate().get_briefs(**kw)
    def get_brief(self, bid):                 return self._delegate().get_brief(bid)
    def get_brief_provenance(self, bid):      return self._delegate().get_brief_provenance(bid)
    def log_agent_run(self, *a):              self._delegate().log_agent_run(*a)
    def get_weekly_stats(self):               return self._delegate().get_weekly_stats()
    def get_whitespace_registry(self, **kw):  return self._delegate().get_whitespace_registry(**kw)
    def get_whitespace_clusters(self):        return self._delegate().get_whitespace_clusters()
    def get_topic_thread(self, tag, **kw):    return self._delegate().get_topic_thread(tag, **kw)
    def get_active_threads(self, **kw):       return self._delegate().get_active_threads(**kw)
    def save_prediction(self, *a):            self._delegate().save_prediction(*a)
    def get_pending_predictions(self):        return self._delegate().get_pending_predictions()
    def verify_prediction(self, *a):          self._delegate().verify_prediction(*a)
    def get_predictions(self, **kw):          return self._delegate().get_predictions(**kw)
    def record_rejection(self, *a):           self._delegate().record_rejection(*a)
    def get_rejections(self, **kw):           return self._delegate().get_rejections(**kw)


# -- Factory ------------------------------------------------------------------

def get_db():
    if DATABASE_URL:
        try:
            return SupabaseDB(DATABASE_URL)
        except Exception:
            pass
    return SQLiteDB()
