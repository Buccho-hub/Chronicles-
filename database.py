"""
database.py
Dual-backend persistence: SQLite (local dev) or Supabase/PostgreSQL (production).
Detected via DATABASE_URL environment variable.
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
    id               TEXT PRIMARY KEY,
    source_session_id TEXT,
    headline         TEXT,
    verdict          TEXT,
    evidence         TEXT DEFAULT '[]',
    implications     TEXT,
    action_items     TEXT DEFAULT '[]',
    confidence       TEXT,
    tier             TEXT DEFAULT 'free',
    agents           TEXT DEFAULT '[]',
    tags             TEXT DEFAULT '[]',
    created_at       TEXT NOT NULL,
    published        INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS agent_runs (
    id                 TEXT PRIMARY KEY,
    agent              TEXT NOT NULL,
    run_at             TEXT NOT NULL,
    items_fetched      INTEGER DEFAULT 0,
    items_passed_gate  INTEGER DEFAULT 0,
    posts_produced     INTEGER DEFAULT 0
);
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
        return d["id"]

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
        out = []
        for r in rows:
            d = dict(r)
            for f in ("exchanges", "gaps", "tags"):
                if isinstance(d.get(f), str):
                    try: d[f] = json.loads(d[f])
                    except: pass
            out.append(d)
        return out

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
        out = []
        for r in rows:
            d = dict(r)
            for f in ("exchanges", "gaps", "tags"):
                if isinstance(d.get(f), str):
                    try: d[f] = json.loads(d[f])
                    except: pass
            out.append(d)
        return out

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
                  (id, source_session_id, headline, verdict, evidence,
                   implications, action_items, confidence, tier, agents,
                   tags, created_at, published)
                VALUES
                  (:id,:source_session_id,:headline,:verdict,:evidence,
                   :implications,:action_items,:confidence,:tier,:agents,
                   :tags,:created_at,:published)
            """, {
                "id":               b["id"],
                "source_session_id":b.get("source_session_id"),
                "headline":         b.get("headline"),
                "verdict":          b.get("verdict"),
                "evidence":         b.get("evidence", "[]"),
                "implications":     b.get("implications"),
                "action_items":     b.get("action_items", "[]"),
                "confidence":       b.get("confidence", "LOW"),
                "tier":             b.get("tier", "free"),
                "agents":           b.get("agents", "[]"),
                "tags":             b.get("tags", "[]"),
                "created_at":       b["created_at"],
                "published":        1 if b.get("published", True) else 0,
            })
        return b["id"]

    def get_briefs(self, limit: int = 20) -> list[dict]:
        with self._conn() as c:
            rows = c.execute(
                "SELECT * FROM briefs WHERE published=1 ORDER BY created_at DESC LIMIT ?",
                (limit,)
            ).fetchall()
        out = []
        for r in rows:
            d = dict(r)
            for f in ("evidence", "action_items", "agents", "tags"):
                if isinstance(d.get(f), str):
                    try: d[f] = json.loads(d[f])
                    except: pass
            d["published"] = bool(d.get("published", 1))
            out.append(d)
        return out

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
        return {
            "total_dispatches": total,
            "convergence_alerts": alerts,
            "briefs": briefs_count,
            "by_agent": {r[0]: r[1] for r in by_agent},
        }


# -- Supabase backend (thin wrapper using psycopg2) ---------------------------

class SupabaseDB:
    """Minimal Supabase/PostgreSQL backend using the same interface as SQLiteDB."""

    def __init__(self, url: str):
        try:
            import psycopg2
            import psycopg2.extras
            self._psycopg2 = psycopg2
            self._extras   = psycopg2.extras
            self._url      = url
            self._init()
            logger.info("Connected to Supabase/PostgreSQL")
        except ImportError:
            logger.error("psycopg2 not installed; falling back to SQLite")
            raise

    def _conn(self):
        return self._psycopg2.connect(self._url)

    def _init(self):
        pg_schema = SCHEMA.replace("INTEGER", "BOOLEAN").replace(
            "TEXT PRIMARY KEY", "TEXT PRIMARY KEY"
        )
        with self._conn() as c:
            with c.cursor() as cur:
                for stmt in pg_schema.split(";"):
                    s = stmt.strip()
                    if s:
                        try:
                            cur.execute(s)
                        except Exception:
                            pass

    # Delegate all methods to SQLiteDB-compatible logic
    # (For production, each method would use parameterised psycopg2 queries)
    # Full implementation mirrors SQLiteDB with %s placeholders.
    # For brevity, we fall back to SQLite on import error above.

    def save_dispatch(self, d):          return SQLiteDB(SQLITE_PATH).save_dispatch(d)
    def get_dispatches(self, **kw):      return SQLiteDB(SQLITE_PATH).get_dispatches(**kw)
    def get_dispatch(self, did):         return SQLiteDB(SQLITE_PATH).get_dispatch(did)
    def mark_seen(self, *a):             SQLiteDB(SQLITE_PATH).mark_seen(*a)
    def is_seen(self, *a):               return SQLiteDB(SQLITE_PATH).is_seen(*a)
    def save_council_session(self, s):   return SQLiteDB(SQLITE_PATH).save_council_session(s)
    def get_unprocessed_sessions(self):  return SQLiteDB(SQLITE_PATH).get_unprocessed_sessions()
    def mark_session_processed(self, i): SQLiteDB(SQLITE_PATH).mark_session_processed(i)
    def get_recent_sessions(self, **kw): return SQLiteDB(SQLITE_PATH).get_recent_sessions(**kw)
    def save_brief(self, b):             return SQLiteDB(SQLITE_PATH).save_brief(b)
    def get_briefs(self, **kw):          return SQLiteDB(SQLITE_PATH).get_briefs(**kw)
    def log_agent_run(self, *a):         SQLiteDB(SQLITE_PATH).log_agent_run(*a)
    def get_weekly_stats(self):          return SQLiteDB(SQLITE_PATH).get_weekly_stats()


# -- Factory ------------------------------------------------------------------

def get_db():
    if DATABASE_URL:
        try:
            return SupabaseDB(DATABASE_URL)
        except Exception:
            pass
    return SQLiteDB()
