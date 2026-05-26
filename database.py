"""
database.py
Dual backend: SQLite (dev) / Supabase REST API (prod).
Detect via SUPABASE_URL + SUPABASE_KEY env vars.
If both present: use Supabase.
If absent: use SQLite.
"""
import os
import json
import sqlite3
import logging
from datetime import datetime, timezone
from typing import Optional, List, Dict, Any

logger = logging.getLogger(__name__)

SUPABASE_URL = os.environ.get("SUPABASE_URL", "")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY", "")
USE_SUPABASE = bool(SUPABASE_URL and SUPABASE_KEY)

supabase: Optional[Any] = None

if USE_SUPABASE:
    try:
        from supabase import create_client, Client
        supabase = create_client(SUPABASE_URL, SUPABASE_KEY)
        logger.info("Supabase client initialized")
    except Exception as e:
        logger.error("Supabase client init failed: %s", e)
        supabase = None
        USE_SUPABASE = False

DB_PATH = os.environ.get("DB_PATH", "chronicles.db")

# -- SQLite helpers -----------------------------------------------------------

def _get_sqlite() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def _init_sqlite_tables():
    """Create SQLite tables if they do not exist."""
    conn = _get_sqlite()
    cursor = conn.cursor()
    cursor.executescript("""
        CREATE TABLE IF NOT EXISTS dispatches (
            id TEXT PRIMARY KEY,
            type TEXT NOT NULL DEFAULT 'dispatch',
            agent TEXT NOT NULL,
            timestamp TEXT NOT NULL,
            body TEXT NOT NULL,
            headline TEXT,
            tags TEXT DEFAULT '[]',
            mentions TEXT DEFAULT '[]',
            reactions TEXT DEFAULT '{}',
            sil_score REAL DEFAULT 0,
            dimensions TEXT DEFAULT '{}',
            raw_data TEXT DEFAULT '{}',
            published INTEGER DEFAULT 1
        );

        CREATE TABLE IF NOT EXISTS seen_items (
            id TEXT PRIMARY KEY,
            agent TEXT NOT NULL,
            seen_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS council_sessions (
            id TEXT PRIMARY KEY,
            source_dispatch_id TEXT,
            topic TEXT,
            exchanges TEXT DEFAULT '[]',
            consensus TEXT,
            dissent TEXT,
            gaps TEXT DEFAULT '[]',
            tags TEXT DEFAULT '[]',
            created_at TEXT NOT NULL,
            processed INTEGER DEFAULT 0
        );

        CREATE TABLE IF NOT EXISTS briefs (
            id TEXT PRIMARY KEY,
            source_session_id TEXT,
            headline TEXT,
            verdict TEXT,
            evidence TEXT DEFAULT '[]',
            implications TEXT,
            action_items TEXT DEFAULT '[]',
            confidence TEXT,
            tier TEXT DEFAULT 'free',
            agents TEXT DEFAULT '[]',
            tags TEXT DEFAULT '[]',
            created_at TEXT NOT NULL,
            published INTEGER DEFAULT 0
        );

        CREATE TABLE IF NOT EXISTS agent_runs (
            id TEXT PRIMARY KEY,
            agent TEXT NOT NULL,
            run_at TEXT NOT NULL,
            items_fetched INTEGER DEFAULT 0,
            items_passed_gate INTEGER DEFAULT 0,
            posts_produced INTEGER DEFAULT 0
        );
    """)
    conn.commit()
    conn.close()


# -- JSON helpers -------------------------------------------------------------

def _to_json(val: Any) -> str:
    if isinstance(val, str):
        return val
    return json.dumps(val)


def _from_json(val: Any) -> Any:
    if not val:
        return {} if isinstance(val, str) and val.startswith("{") else []
    try:
        return json.loads(val)
    except Exception:
        return val


# -- Supabase helpers ---------------------------------------------------------

def _supabase_upsert(table: str, payload: dict) -> bool:
    if not supabase:
        return False
    try:
        supabase.table(table).upsert(payload).execute()
        return True
    except Exception as e:
        logger.error("Supabase upsert to %s failed: %s", table, e)
        return False


def _supabase_insert(table: str, payload: dict) -> bool:
    if not supabase:
        return False
    try:
        supabase.table(table).insert(payload).execute()
        return True
    except Exception as e:
        logger.error("Supabase insert to %s failed: %s", table, e)
        return False


def _supabase_select(table: str, columns: str = "*", filters: dict = None,
                     order_by: str = None, desc: bool = True, limit: int = None) -> List[dict]:
    if not supabase:
        return []
    try:
        q = supabase.table(table).select(columns)
        if filters:
            for col, val in filters.items():
                q = q.eq(col, val)
        if order_by:
            q = q.order(order_by, desc=desc)
        if limit:
            q = q.limit(limit)
        resp = q.execute()
        return resp.data or []
    except Exception as e:
        logger.error("Supabase select from %s failed: %s", table, e)
        return []


def _supabase_update(table: str, payload: dict, filters: dict) -> bool:
    if not supabase:
        return False
    try:
        q = supabase.table(table).update(payload)
        for col, val in filters.items():
            q = q.eq(col, val)
        q.execute()
        return True
    except Exception as e:
        logger.error("Supabase update on %s failed: %s", table, e)
        return False


# -- Unified DB class ---------------------------------------------------------

class ChroniclesDB:
    """Unified interface: SQLite or Supabase behind the same methods."""

    def __init__(self):
        if not USE_SUPABASE:
            _init_sqlite_tables()

    # -- dispatches ------------------------------------------------------------

    def save_dispatch(self, dispatch: dict) -> str:
        import uuid
        dispatch_id = dispatch.get("id") or str(uuid.uuid4())
        payload = {
            "id": dispatch_id,
            "type": dispatch.get("type", "dispatch"),
            "agent": dispatch.get("agent", ""),
            "timestamp": dispatch.get("timestamp") or _now(),
            "body": dispatch.get("body", ""),
            "headline": dispatch.get("headline"),
            "tags": _to_json(dispatch.get("tags", [])),
            "mentions": _to_json(dispatch.get("mentions", [])),
            "reactions": _to_json(dispatch.get("reactions", {})),
            "sil_score": dispatch.get("sil_score", 0),
            "dimensions": _to_json(dispatch.get("dimensions", {})),
            "raw_data": _to_json(dispatch.get("raw_data", {})),
            "published": bool(dispatch.get("published", True)),
        }
        if USE_SUPABASE:
            _supabase_upsert("dispatches", payload)
            return dispatch_id
        conn = _get_sqlite()
        cursor = conn.cursor()
        cursor.execute("""
            INSERT OR REPLACE INTO dispatches
            (id, type, agent, timestamp, body, headline, tags, mentions, reactions,
             sil_score, dimensions, raw_data, published)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, tuple(payload.values()))
        conn.commit()
        conn.close()
        return dispatch_id

    def get_dispatches(self, limit: int = 50, type_filter: str = None,
                       agent_filter: str = None) -> List[dict]:
        if USE_SUPABASE:
            filters = {}
            if type_filter:
                filters["type"] = type_filter
            if agent_filter:
                filters["agent"] = agent_filter
            rows = _supabase_select("dispatches", filters=filters,
                                    order_by="timestamp", desc=True, limit=limit)
        else:
            conn = _get_sqlite()
            cursor = conn.cursor()
            sql = "SELECT * FROM dispatches WHERE 1=1"
            params = []
            if type_filter:
                sql += " AND type = ?"
                params.append(type_filter)
            if agent_filter:
                sql += " AND agent = ?"
                params.append(agent_filter)
            sql += " ORDER BY timestamp DESC LIMIT ?"
            params.append(limit)
            cursor.execute(sql, params)
            rows = [dict(r) for r in cursor.fetchall()]
            conn.close()

        for r in rows:
            for f in ("tags", "mentions", "reactions", "dimensions", "raw_data"):
                r[f] = _from_json(r.get(f))
        return rows

    # -- seen items ------------------------------------------------------------

    def is_seen(self, item_id: str, agent: str) -> bool:
        if USE_SUPABASE:
            rows = _supabase_select("seen_items", filters={"id": item_id, "agent": agent}, limit=1)
            return bool(rows)
        conn = _get_sqlite()
        cursor = conn.cursor()
        cursor.execute("SELECT 1 FROM seen_items WHERE id = ? AND agent = ?", (item_id, agent))
        seen = cursor.fetchone() is not None
        conn.close()
        return seen

    def mark_seen(self, item_id: str, agent: str) -> None:
        payload = {"id": item_id, "agent": agent, "seen_at": _now()}
        if USE_SUPABASE:
            _supabase_upsert("seen_items", payload)
            return
        conn = _get_sqlite()
        cursor = conn.cursor()
        cursor.execute("INSERT OR REPLACE INTO seen_items (id, agent, seen_at) VALUES (?, ?, ?)",
                       (item_id, agent, _now()))
        conn.commit()
        conn.close()

    # -- council sessions ------------------------------------------------------

    def save_session(self, session: dict) -> str:
        import uuid
        sid = session.get("id") or str(uuid.uuid4())
        payload = {
            "id": sid,
            "source_dispatch_id": session.get("source_dispatch_id"),
            "topic": session.get("topic"),
            "exchanges": _to_json(session.get("exchanges", [])),
            "consensus": session.get("consensus"),
            "dissent": session.get("dissent"),
            "gaps": _to_json(session.get("gaps", [])),
            "tags": _to_json(session.get("tags", [])),
            "created_at": session.get("created_at") or _now(),
            "processed": bool(session.get("processed", False)),
        }
        if USE_SUPABASE:
            _supabase_upsert("council_sessions", payload)
            return sid
        conn = _get_sqlite()
        cursor = conn.cursor()
        cursor.execute("""
            INSERT OR REPLACE INTO council_sessions
            (id, source_dispatch_id, topic, exchanges, consensus, dissent, gaps, tags, created_at, processed)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, tuple(payload.values()))
        conn.commit()
        conn.close()
        return sid

    def get_recent_sessions(self, limit: int = 20) -> List[dict]:
        if USE_SUPABASE:
            rows = _supabase_select("council_sessions", order_by="created_at", desc=True, limit=limit)
        else:
            conn = _get_sqlite()
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM council_sessions ORDER BY created_at DESC LIMIT ?", (limit,))
            rows = [dict(r) for r in cursor.fetchall()]
            conn.close()
        for r in rows:
            for f in ("exchanges", "gaps", "tags"):
                r[f] = _from_json(r.get(f))
        return rows

    def get_unprocessed_sessions(self) -> List[dict]:
        if USE_SUPABASE:
            rows = _supabase_select("council_sessions", filters={"processed": False},
                                    order_by="created_at", desc=True)
        else:
            conn = _get_sqlite()
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM council_sessions WHERE processed = 0 ORDER BY created_at DESC")
            rows = [dict(r) for r in cursor.fetchall()]
            conn.close()
        for r in rows:
            for f in ("exchanges", "gaps", "tags"):
                r[f] = _from_json(r.get(f))
        return rows

    def mark_session_processed(self, session_id: str) -> None:
        if USE_SUPABASE:
            _supabase_update("council_sessions", {"processed": True}, {"id": session_id})
            return
        conn = _get_sqlite()
        cursor = conn.cursor()
        cursor.execute("UPDATE council_sessions SET processed = 1 WHERE id = ?", (session_id,))
        conn.commit()
        conn.close()

    # -- briefs ----------------------------------------------------------------

    def save_brief(self, brief: dict) -> str:
        import uuid
        bid = brief.get("id") or str(uuid.uuid4())
        payload = {
            "id": bid,
            "source_session_id": brief.get("source_session_id"),
            "headline": brief.get("headline"),
            "verdict": brief.get("verdict"),
            "evidence": _to_json(brief.get("evidence", [])),
            "implications": brief.get("implications"),
            "action_items": _to_json(brief.get("action_items", [])),
            "confidence": brief.get("confidence"),
            "tier": brief.get("tier", "free"),
            "agents": _to_json(brief.get("agents", [])),
            "tags": _to_json(brief.get("tags", [])),
            "created_at": brief.get("created_at") or _now(),
            "published": bool(brief.get("published", False)),
        }
        if USE_SUPABASE:
            _supabase_upsert("briefs", payload)
            return bid
        conn = _get_sqlite()
        cursor = conn.cursor()
        cursor.execute("""
            INSERT OR REPLACE INTO briefs
            (id, source_session_id, headline, verdict, evidence, implications,
             action_items, confidence, tier, agents, tags, created_at, published)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, tuple(payload.values()))
        conn.commit()
        conn.close()
        return bid

    def get_briefs(self, limit: int = 20) -> List[dict]:
        if USE_SUPABASE:
            rows = _supabase_select("briefs", filters={"published": True},
                                    order_by="created_at", desc=True, limit=limit)
        else:
            conn = _get_sqlite()
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM briefs WHERE published = 1 ORDER BY created_at DESC LIMIT ?", (limit,))
            rows = [dict(r) for r in cursor.fetchall()]
            conn.close()
        for r in rows:
            for f in ("evidence", "action_items", "agents", "tags"):
                r[f] = _from_json(r.get(f))
        return rows

    # -- agent runs ------------------------------------------------------------

    def log_agent_run(self, agent: str, fetched: int = 0, passed: int = 0, produced: int = 0) -> None:
        import uuid
        payload = {
            "id": str(uuid.uuid4()),
            "agent": agent,
            "run_at": _now(),
            "items_fetched": fetched,
            "items_passed_gate": passed,
            "posts_produced": produced,
        }
        if USE_SUPABASE:
            _supabase_insert("agent_runs", payload)
            return
        conn = _get_sqlite()
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO agent_runs (id, agent, run_at, items_fetched, items_passed_gate, posts_produced)
            VALUES (?, ?, ?, ?, ?, ?)
        """, tuple(payload.values()))
        conn.commit()
        conn.close()

    def get_weekly_stats(self) -> dict:
        if USE_SUPABASE:
            # Simplified for Supabase — count queries via REST are limited
            return {
                "dispatches_7d": 0,
                "convergences_7d": 0,
                "briefs_7d": 0,
                "last_run": _now(),
            }
        conn = _get_sqlite()
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM dispatches WHERE timestamp > datetime('now', '-7 days')")
        dispatches_7d = cursor.fetchone()[0]
        cursor.execute("SELECT COUNT(*) FROM dispatches WHERE type = 'convergence_alert' AND timestamp > datetime('now', '-7 days')")
        convergences_7d = cursor.fetchone()[0]
        cursor.execute("SELECT COUNT(*) FROM briefs WHERE created_at > datetime('now', '-7 days')")
        briefs_7d = cursor.fetchone()[0]
        cursor.execute("SELECT MAX(run_at) FROM agent_runs")
        row = cursor.fetchone()
        last_run = row[0] if row and row[0] else _now()
        conn.close()
        return {
            "dispatches_7d": dispatches_7d,
            "convergences_7d": convergences_7d,
            "briefs_7d": briefs_7d,
            "last_run": last_run,
        }


# -- Singleton ----------------------------------------------------------------

_db_instance: Optional[ChroniclesDB] = None


def get_db() -> ChroniclesDB:
    global _db_instance
    if _db_instance is None:
        _db_instance = ChroniclesDB()
    return _db_instance


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()
