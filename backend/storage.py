"""
Persistent storage for OpenCouncil.

Supports two backends:
  - SQLite (local development) — zero infrastructure, file-based
  - PostgreSQL (Supabase/HF Spaces) — persistent, scalable

Switch via DATABASE_URL env var:
  - If DATABASE_URL is set → use PostgreSQL
  - Otherwise → use SQLite (local data/ directory)
"""

import json
import logging
import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from models.schemas import Minutes, Summary, SummaryResponse, Volunteer, VerificationSession

logger = logging.getLogger(__name__)

# --- Load .env file if present (fallback for HF Spaces when secrets aren't working) ---

_env_file = Path(__file__).parent / ".env"
if _env_file.exists():
    with open(_env_file) as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, _, val = line.partition("=")
                key = key.strip()
                val = val.strip().strip("\"'")
                if key not in os.environ:  # Don't override existing env vars
                    os.environ[key] = val

# --- Backend Selection ---

USE_POSTGRES = bool(os.getenv("DATABASE_URL"))

# SQLite paths — always defined so we can fall back
if os.getenv("VERCEL"):
    DB_DIR = Path("/tmp/opencouncil_data")
else:
    DB_DIR = Path(__file__).parent / "data"
DB_PATH = DB_DIR / "opencouncil.db"

if USE_POSTGRES:
    from urllib.parse import urlparse, unquote

    def _get_pg_conn():
        """Get a PostgreSQL connection.

        Parses DATABASE_URL manually to handle special characters in passwords
        (e.g. Supabase Transaction Pooler connection strings with `]`, `@`, etc.).
        """
        import psycopg2
        import psycopg2.extras
        raw_url = os.environ["DATABASE_URL"]
        parsed = urlparse(raw_url)

        # Build kwargs from parsed URL — this avoids psycopg2's own URL parser
        # which can choke on special characters in the password.
        kwargs = {
            "host": parsed.hostname,
            "port": parsed.port or 6543,
            "dbname": parsed.path.lstrip("/"),
            "user": parsed.username,
            "password": unquote(parsed.password) if parsed.password else "",
        }

        # Handle SSL mode from query params if present (e.g. ?sslmode=require)
        if parsed.query:
            qs = dict(q.split("=", 1) for q in parsed.query.split("&") if "=" in q)
            sslmode = qs.get("sslmode")
            if sslmode:
                kwargs["sslmode"] = sslmode

        conn = psycopg2.connect(**kwargs)
        conn.autocommit = False
        return conn


# --- Initialization ---


def init_db():
    """Initialize the database schema.

    Tries PostgreSQL first if DATABASE_URL is set, falls back to SQLite
    on connection failure. This allows local development without a running
    PostgreSQL instance even when DATABASE_URL is configured.
    """
    global USE_POSTGRES
    if USE_POSTGRES:
        try:
            _init_pg()
            return
        except Exception as e:
            print(f"[WARN] PostgreSQL connection failed: {e}")
            print("[WARN] Falling back to SQLite for local development.")
            USE_POSTGRES = False
    # Fall back to SQLite
    _init_sqlite()


def _init_sqlite():
    """Initialize SQLite schema — minutes, summaries, volunteers, verification_sessions."""
    DB_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH))
    try:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS minutes (
                id TEXT PRIMARY KEY,
                city TEXT NOT NULL DEFAULT 'Paris',
                state TEXT NOT NULL DEFAULT 'TX',
                meeting_date TEXT NOT NULL,
                meeting_type TEXT NOT NULL DEFAULT 'City Council Meeting',
                title TEXT NOT NULL,
                url TEXT NOT NULL DEFAULT '',
                document_url TEXT,
                raw_text TEXT,
                summary TEXT,
                source TEXT DEFAULT 'laserfiche',
                ingested_at TEXT NOT NULL DEFAULT (datetime('now')),
                created_at TEXT NOT NULL DEFAULT (datetime('now')),
                updated_at TEXT NOT NULL DEFAULT (datetime('now'))
            );

            CREATE TABLE IF NOT EXISTS minutes_summaries (
                minutes_id TEXT PRIMARY KEY,
                meeting_date TEXT NOT NULL,
                meeting_type TEXT NOT NULL,
                summary TEXT NOT NULL,
                key_decisions TEXT NOT NULL DEFAULT '[]',
                budget_items TEXT NOT NULL DEFAULT '[]',
                public_comment_opportunities TEXT NOT NULL DEFAULT '[]',
                items TEXT NOT NULL DEFAULT '[]',
                big_picture TEXT NOT NULL DEFAULT '',
                what_you_can_do TEXT NOT NULL DEFAULT '[]',
                model_used TEXT NOT NULL DEFAULT 'deepseek-chat',
                created_at TEXT NOT NULL DEFAULT (datetime('now')),
                updated_at TEXT NOT NULL DEFAULT (datetime('now')),
                FOREIGN KEY (minutes_id) REFERENCES minutes(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS summaries (
                id TEXT PRIMARY KEY DEFAULT (lower(hex(randomblob(16)))),
                minutes_id INTEGER NOT NULL REFERENCES minutes(id) ON DELETE CASCADE,
                summary TEXT NOT NULL,
                key_decisions TEXT NOT NULL DEFAULT '[]',
                budget_items TEXT NOT NULL DEFAULT '[]',
                public_comment_opportunities TEXT NOT NULL DEFAULT '[]',
                items TEXT NOT NULL DEFAULT '[]',
                big_picture TEXT,
                what_you_can_do TEXT NOT NULL DEFAULT '[]',
                category TEXT,
                neighborhood_impact TEXT,
                status TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'verified', 'rejected')),
                verified_by TEXT REFERENCES volunteers(user_id),
                verified_at TEXT,
                rejection_reason TEXT,
                social_posted INTEGER NOT NULL DEFAULT 0,
                image_url TEXT,
                model_used TEXT,
                created_at TEXT NOT NULL DEFAULT (datetime('now')),
                updated_at TEXT NOT NULL DEFAULT (datetime('now'))
            );

            CREATE TABLE IF NOT EXISTS volunteers (
                user_id TEXT PRIMARY KEY,
                email TEXT UNIQUE NOT NULL,
                full_name TEXT NOT NULL,
                school TEXT,
                hours_earned REAL NOT NULL DEFAULT 0.00,
                is_active INTEGER NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL DEFAULT (datetime('now')),
                updated_at TEXT NOT NULL DEFAULT (datetime('now'))
            );

            CREATE TABLE IF NOT EXISTS verification_sessions (
                id TEXT PRIMARY KEY DEFAULT (lower(hex(randomblob(16)))),
                volunteer_id TEXT NOT NULL REFERENCES volunteers(user_id) ON DELETE CASCADE,
                summary_id TEXT NOT NULL REFERENCES summaries(id) ON DELETE CASCADE,
                started_at TEXT NOT NULL DEFAULT (datetime('now')),
                ended_at TEXT,
                duration_seconds INTEGER,
                action TEXT CHECK (action IN ('approved', 'rejected')),
                notes TEXT
            );

            CREATE INDEX IF NOT EXISTS idx_minutes_date ON minutes(meeting_date DESC);
            CREATE INDEX IF NOT EXISTS idx_minutes_city ON minutes(city, state);
            CREATE INDEX IF NOT EXISTS idx_summaries_status ON summaries(status);
            CREATE INDEX IF NOT EXISTS idx_summaries_verified_by ON summaries(verified_by);
            CREATE INDEX IF NOT EXISTS idx_verification_sessions_volunteer ON verification_sessions(volunteer_id);
            CREATE INDEX IF NOT EXISTS idx_verification_sessions_summary ON verification_sessions(summary_id);
            CREATE INDEX IF NOT EXISTS idx_volunteers_email ON volunteers(email);
        """)
        conn.commit()
    finally:
        conn.close()


def _init_pg():
    """Initialize PostgreSQL schema — minutes, summaries, volunteers, verification_sessions."""
    conn = _get_pg_conn()
    try:
        with conn.cursor() as cur:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS minutes (
                    id TEXT PRIMARY KEY,
                    city TEXT NOT NULL DEFAULT 'Paris',
                    state TEXT NOT NULL DEFAULT 'TX',
                    meeting_date TEXT NOT NULL,
                    meeting_type TEXT NOT NULL DEFAULT 'City Council Meeting',
                    title TEXT NOT NULL,
                    url TEXT NOT NULL DEFAULT '',
                    document_url TEXT,
                    raw_text TEXT,
                    summary TEXT,
                    source TEXT DEFAULT 'laserfiche',
                    ingested_at TIMESTAMP NOT NULL DEFAULT NOW(),
                    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
                    updated_at TIMESTAMP NOT NULL DEFAULT NOW()
                );
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS minutes_summaries (
                    minutes_id TEXT PRIMARY KEY REFERENCES minutes(id) ON DELETE CASCADE,
                    meeting_date TEXT NOT NULL,
                    meeting_type TEXT NOT NULL,
                    summary TEXT NOT NULL,
                    key_decisions TEXT NOT NULL DEFAULT '[]',
                    budget_items TEXT NOT NULL DEFAULT '[]',
                    public_comment_opportunities TEXT NOT NULL DEFAULT '[]',
                    items TEXT NOT NULL DEFAULT '[]',
                    big_picture TEXT NOT NULL DEFAULT '',
                    what_you_can_do TEXT NOT NULL DEFAULT '[]',
                    model_used TEXT NOT NULL DEFAULT 'deepseek-chat',
                    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
                    updated_at TIMESTAMP NOT NULL DEFAULT NOW()
                );
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS summaries (
                    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                    minutes_id TEXT NOT NULL REFERENCES minutes(id) ON DELETE CASCADE,
                    summary TEXT NOT NULL,
                    key_decisions JSONB DEFAULT '[]',
                    budget_items JSONB DEFAULT '[]',
                    public_comment_opportunities JSONB DEFAULT '[]',
                    items JSONB DEFAULT '[]',
                    big_picture TEXT,
                    what_you_can_do JSONB DEFAULT '[]',
                    category TEXT,
                    neighborhood_impact TEXT,
                    status TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'verified', 'rejected')),
                    verified_by UUID REFERENCES volunteers(user_id),
                    verified_at TIMESTAMPTZ,
                    rejection_reason TEXT,
                    social_posted BOOLEAN DEFAULT FALSE,
                    image_url TEXT,
                    model_used TEXT,
                    created_at TIMESTAMPTZ DEFAULT NOW(),
                    updated_at TIMESTAMPTZ DEFAULT NOW()
                );
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS volunteers (
                    user_id UUID PRIMARY KEY,
                    email TEXT UNIQUE NOT NULL,
                    full_name TEXT NOT NULL,
                    school TEXT,
                    hours_earned DECIMAL(10,2) DEFAULT 0.00,
                    is_active BOOLEAN DEFAULT TRUE,
                    created_at TIMESTAMPTZ DEFAULT NOW(),
                    updated_at TIMESTAMPTZ DEFAULT NOW()
                );
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS verification_sessions (
                    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                    volunteer_id UUID NOT NULL REFERENCES volunteers(user_id) ON DELETE CASCADE,
                    summary_id UUID NOT NULL REFERENCES summaries(id) ON DELETE CASCADE,
                    started_at TIMESTAMPTZ DEFAULT NOW(),
                    ended_at TIMESTAMPTZ,
                    duration_seconds INTEGER,
                    action TEXT CHECK (action IN ('approved', 'rejected')),
                    notes TEXT
                );
            """)
            cur.execute("""
                CREATE INDEX IF NOT EXISTS idx_minutes_date ON minutes(meeting_date DESC);
            """)
            cur.execute("""
                CREATE INDEX IF NOT EXISTS idx_minutes_city ON minutes(city, state);
            """)
            cur.execute("""
                CREATE INDEX IF NOT EXISTS idx_summaries_status ON summaries(status);
            """)
            cur.execute("""
                CREATE INDEX IF NOT EXISTS idx_summaries_verified_by ON summaries(verified_by);
            """)
            cur.execute("""
                CREATE INDEX IF NOT EXISTS idx_verification_sessions_volunteer ON verification_sessions(volunteer_id);
            """)
            cur.execute("""
                CREATE INDEX IF NOT EXISTS idx_verification_sessions_summary ON verification_sessions(summary_id);
            """)
            cur.execute("""
                CREATE INDEX IF NOT EXISTS idx_volunteers_email ON volunteers(email);
            """)
            # Migration: add big_picture and what_you_can_do columns if they don't exist
            # Safe to run multiple times — IF NOT EXISTS prevents errors
            try:
                cur.execute("""
                    ALTER TABLE minutes_summaries
                    ADD COLUMN IF NOT EXISTS big_picture TEXT NOT NULL DEFAULT ''
                """)
            except Exception:
                pass  # Some PG versions don't support IF NOT EXISTS for columns
            try:
                cur.execute("""
                    ALTER TABLE minutes_summaries
                    ADD COLUMN IF NOT EXISTS what_you_can_do TEXT NOT NULL DEFAULT '[]'
                """)
            except Exception:
                pass
        conn.commit()
    finally:
        conn.close()


# --- Minutes Storage ---


def save_minutes(minutes: Minutes) -> None:
    """Save or update minutes in the database."""
    if USE_POSTGRES:
        _save_minutes_pg(minutes)
    else:
        _save_minutes_sqlite(minutes)


def _save_minutes_sqlite(minutes: Minutes) -> None:
    """Save minutes to SQLite."""
    conn = sqlite3.connect(str(DB_PATH))
    try:
        conn.execute(
            """INSERT OR REPLACE INTO minutes
               (id, city, state, meeting_date, meeting_type, title, url,
                document_url, raw_text, summary, source, ingested_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                minutes.id, minutes.city, minutes.state,
                minutes.meeting_date.isoformat(), minutes.meeting_type,
                minutes.title, minutes.url, minutes.document_url,
                minutes.raw_text, minutes.summary, minutes.source,
                minutes.ingested_at.isoformat(),
            ),
        )
        conn.commit()
    finally:
        conn.close()


def _save_minutes_pg(minutes: Minutes) -> None:
    """Save minutes to PostgreSQL."""
    conn = _get_pg_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """INSERT INTO minutes
                   (id, city, state, meeting_date, meeting_type, title, url,
                    document_url, raw_text, summary, source, ingested_at)
                   VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                   ON CONFLICT (id) DO UPDATE SET
                       city = EXCLUDED.city,
                       state = EXCLUDED.state,
                       meeting_date = EXCLUDED.meeting_date,
                       meeting_type = EXCLUDED.meeting_type,
                       title = EXCLUDED.title,
                       url = EXCLUDED.url,
                       document_url = EXCLUDED.document_url,
                       raw_text = EXCLUDED.raw_text,
                       summary = EXCLUDED.summary,
                       source = EXCLUDED.source,
                       updated_at = NOW()""",
                (
                    minutes.id, minutes.city, minutes.state,
                    minutes.meeting_date.isoformat(), minutes.meeting_type,
                    minutes.title, minutes.url, minutes.document_url,
                    minutes.raw_text, minutes.summary, minutes.source,
                    minutes.ingested_at.isoformat(),
                ),
            )
        conn.commit()
    finally:
        conn.close()


def get_minutes(minutes_id: str) -> Optional[Minutes]:
    """Get minutes by ID from database."""
    if USE_POSTGRES:
        return _get_minutes_pg(minutes_id)
    return _get_minutes_sqlite(minutes_id)


def _get_minutes_sqlite(minutes_id: str) -> Optional[Minutes]:
    """Get minutes from SQLite."""
    def _ensure_tz(dt: datetime) -> datetime:
        if dt is not None and dt.tzinfo is None:
            return dt.replace(tzinfo=timezone.utc)
        return dt

    conn = sqlite3.connect(str(DB_PATH))
    try:
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT * FROM minutes WHERE id = ?", (minutes_id,)
        ).fetchone()
        if not row:
            return None
        return Minutes(
            id=row["id"],
            city=row["city"],
            state=row["state"],
            meeting_date=_ensure_tz(datetime.fromisoformat(row["meeting_date"])),
            meeting_type=row["meeting_type"],
            title=row["title"],
            url=row["url"],
            document_url=row["document_url"],
            raw_text=row["raw_text"],
            summary=row["summary"],
            source=row["source"],
        )
    finally:
        conn.close()


def _get_minutes_pg(minutes_id: str) -> Optional[Minutes]:
    """Get minutes from PostgreSQL."""
    def _ensure_tz(dt: datetime) -> datetime:
        if dt is not None and dt.tzinfo is None:
            return dt.replace(tzinfo=timezone.utc)
        return dt

    conn = _get_pg_conn()
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                "SELECT * FROM minutes WHERE id = %s", (minutes_id,)
            )
            row = cur.fetchone()
            if not row:
                return None
            meeting_date = row["meeting_date"]
            if isinstance(meeting_date, str):
                meeting_date = _ensure_tz(datetime.fromisoformat(meeting_date))
            else:
                meeting_date = _ensure_tz(meeting_date)
            return Minutes(
                id=row["id"],
                city=row["city"],
                state=row["state"],
                meeting_date=meeting_date,
                meeting_type=row["meeting_type"],
                title=row["title"],
                url=row["url"],
                document_url=row["document_url"],
                raw_text=row["raw_text"],
                summary=row["summary"],
                source=row["source"],
            )
    finally:
        conn.close()


def list_minutes(limit: int = 10) -> list[dict]:
    """List recent minutes from database."""
    if USE_POSTGRES:
        return _list_minutes_pg(limit)
    return _list_minutes_sqlite(limit)


def _list_minutes_sqlite(limit: int = 10) -> list[dict]:
    """List minutes from SQLite."""
    conn = sqlite3.connect(str(DB_PATH))
    try:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            """SELECT id, city, state, meeting_date, meeting_type, title, url,
                      document_url, source
               FROM minutes
               ORDER BY meeting_date DESC
               LIMIT ?""",
            (limit,),
        ).fetchall()
        return [
            {
                "id": r["id"],
                "title": r["title"],
                "meeting_date": r["meeting_date"],
                "meeting_type": r["meeting_type"],
                "url": r["url"],
                "document_url": r["document_url"],
            }
            for r in rows
        ]
    finally:
        conn.close()


def _list_minutes_pg(limit: int = 10) -> list[dict]:
    """List minutes from PostgreSQL."""
    conn = _get_pg_conn()
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                """SELECT id, city, state, meeting_date, meeting_type, title, url,
                          document_url, source
                   FROM minutes
                   ORDER BY meeting_date DESC
                   LIMIT %s""",
                (limit,),
            )
            rows = cur.fetchall()
            return [
                {
                    "id": r["id"],
                    "title": r["title"],
                    "meeting_date": r["meeting_date"],
                    "meeting_type": r["meeting_type"],
                    "url": r["url"],
                    "document_url": r["document_url"],
                }
                for r in rows
            ]
    finally:
        conn.close()


# --- Minutes Summaries Storage ---


def save_minutes_summary(minutes_id: str, summary: SummaryResponse) -> None:
    """Save a summary for minutes."""
    if USE_POSTGRES:
        _save_minutes_summary_pg(minutes_id, summary)
    else:
        _save_minutes_summary_sqlite(minutes_id, summary)


def _save_minutes_summary_sqlite(minutes_id: str, summary: SummaryResponse) -> None:
    """Save minutes summary to SQLite."""
    conn = sqlite3.connect(str(DB_PATH))
    try:
        conn.execute(
            """INSERT OR REPLACE INTO minutes_summaries
               (minutes_id, meeting_date, meeting_type, summary,
                key_decisions, budget_items, public_comment_opportunities, items,
                big_picture, what_you_can_do)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                minutes_id,
                summary.meeting_date.isoformat(),
                summary.meeting_type,
                summary.summary,
                json.dumps([k.model_dump() if hasattr(k, 'model_dump') else k for k in summary.key_decisions]),
                json.dumps([b.model_dump() if hasattr(b, 'model_dump') else b for b in summary.budget_items]),
                json.dumps([p.model_dump() if hasattr(p, 'model_dump') else p for p in summary.public_comment_opportunities]),
                json.dumps([i.model_dump() if hasattr(i, 'model_dump') else i for i in summary.items]),
                summary.big_picture,
                json.dumps([w.model_dump() if hasattr(w, 'model_dump') else w for w in summary.what_you_can_do]),
            ),
        )
        conn.commit()
    finally:
        conn.close()


def _save_minutes_summary_pg(minutes_id: str, summary: SummaryResponse) -> None:
    """Save minutes summary to PostgreSQL."""
    conn = _get_pg_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """INSERT INTO minutes_summaries
                   (minutes_id, meeting_date, meeting_type, summary,
                    key_decisions, budget_items, public_comment_opportunities, items,
                    big_picture, what_you_can_do)
                   VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                   ON CONFLICT (minutes_id) DO UPDATE SET
                       meeting_date = EXCLUDED.meeting_date,
                       meeting_type = EXCLUDED.meeting_type,
                       summary = EXCLUDED.summary,
                       key_decisions = EXCLUDED.key_decisions,
                       budget_items = EXCLUDED.budget_items,
                       public_comment_opportunities = EXCLUDED.public_comment_opportunities,
                       items = EXCLUDED.items,
                       big_picture = EXCLUDED.big_picture,
                       what_you_can_do = EXCLUDED.what_you_can_do,
                       updated_at = NOW()""",
                (
                    minutes_id,
                    summary.meeting_date.isoformat(),
                    summary.meeting_type,
                    summary.summary,
                    json.dumps([k.model_dump() if hasattr(k, 'model_dump') else k for k in summary.key_decisions]),
                    json.dumps([b.model_dump() if hasattr(b, 'model_dump') else b for b in summary.budget_items]),
                    json.dumps([p.model_dump() if hasattr(p, 'model_dump') else p for p in summary.public_comment_opportunities]),
                    json.dumps([i.model_dump() if hasattr(i, 'model_dump') else i for i in summary.items]),
                    summary.big_picture,
                    json.dumps([w.model_dump() if hasattr(w, 'model_dump') else w for w in summary.what_you_can_do]),
                ),
            )
        conn.commit()
    finally:
        conn.close()


def get_minutes_summary(minutes_id: str) -> Optional[SummaryResponse]:
    """Get summary for minutes by ID."""
    if USE_POSTGRES:
        return _get_minutes_summary_pg(minutes_id)
    return _get_minutes_summary_sqlite(minutes_id)


def _get_minutes_summary_sqlite(minutes_id: str) -> Optional[SummaryResponse]:
    """Get minutes summary from SQLite."""
    def _ensure_tz(dt: datetime) -> datetime:
        if dt is not None and dt.tzinfo is None:
            return dt.replace(tzinfo=timezone.utc)
        return dt

    conn = sqlite3.connect(str(DB_PATH))
    try:
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT * FROM minutes_summaries WHERE minutes_id = ?", (minutes_id,)
        ).fetchone()
        if not row:
            return None
        return SummaryResponse(
            minutes_id=row["minutes_id"],
            meeting_date=_ensure_tz(datetime.fromisoformat(row["meeting_date"])),
            meeting_type=row["meeting_type"],
            summary=row["summary"],
            key_decisions=json.loads(row["key_decisions"]),
            budget_items=json.loads(row["budget_items"]),
            public_comment_opportunities=json.loads(row["public_comment_opportunities"]),
            items=json.loads(row["items"]),
            big_picture=row["big_picture"] if "big_picture" in row.keys() else "",
            what_you_can_do=json.loads(row["what_you_can_do"]) if "what_you_can_do" in row.keys() else [],
        )
    finally:
        conn.close()


def _get_minutes_summary_pg(minutes_id: str) -> Optional[SummaryResponse]:
    """Get minutes summary from PostgreSQL."""
    def _ensure_tz(dt: datetime) -> datetime:
        if dt is not None and dt.tzinfo is None:
            return dt.replace(tzinfo=timezone.utc)
        return dt

    conn = _get_pg_conn()
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                "SELECT * FROM minutes_summaries WHERE minutes_id = %s", (minutes_id,)
            )
            row = cur.fetchone()
            if not row:
                return None
            meeting_date = row["meeting_date"]
            if isinstance(meeting_date, str):
                meeting_date = _ensure_tz(datetime.fromisoformat(meeting_date))
            else:
                meeting_date = _ensure_tz(meeting_date)
            return SummaryResponse(
                minutes_id=row["minutes_id"],
                meeting_date=meeting_date,
                meeting_type=row["meeting_type"],
                summary=row["summary"],
                key_decisions=json.loads(row["key_decisions"]),
                budget_items=json.loads(row["budget_items"]),
                public_comment_opportunities=json.loads(row["public_comment_opportunities"]),
                items=json.loads(row["items"]),
                big_picture=row.get("big_picture", ""),
                what_you_can_do=json.loads(row.get("what_you_can_do", "[]")),
            )
    finally:
        conn.close()


def minutes_summary_exists(minutes_id: str) -> bool:
    """Check if a summary already exists for these minutes."""
    if USE_POSTGRES:
        return _minutes_summary_exists_pg(minutes_id)
    return _minutes_summary_exists_sqlite(minutes_id)


def _minutes_summary_exists_sqlite(minutes_id: str) -> bool:
    """Check minutes summary existence in SQLite."""
    conn = sqlite3.connect(str(DB_PATH))
    try:
        row = conn.execute(
            "SELECT 1 FROM minutes_summaries WHERE minutes_id = ?", (minutes_id,)
        ).fetchone()
        return row is not None
    finally:
        conn.close()


# --- Database Reset ---


def reset_database() -> None:
    """Delete ALL minutes and summaries from the database.
    
    This is used when the user wants to "reset the articles" —
    clearing out stale data so fresh minutes can be fetched.
    """
    if USE_POSTGRES:
        _reset_database_pg()
    else:
        _reset_database_sqlite()


def _reset_database_sqlite() -> None:
    """Delete all minutes and summaries from SQLite."""
    conn = sqlite3.connect(str(DB_PATH))
    try:
        conn.execute("DELETE FROM minutes_summaries")
        conn.execute("DELETE FROM minutes")
        conn.commit()
        print("[DB] SQLite database reset — all minutes and summaries deleted.")
    finally:
        conn.close()


def _reset_database_pg() -> None:
    """Delete all minutes and summaries from PostgreSQL."""
    conn = _get_pg_conn()
    try:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM minutes_summaries")
            cur.execute("DELETE FROM minutes")
        conn.commit()
        print("[DB] PostgreSQL database reset — all minutes and summaries deleted.")
    finally:
        conn.close()


# =============================================================================
# New Tables: summaries, volunteers, verification_sessions
# =============================================================================


# --- Summaries CRUD ---


def save_summary(summary: Summary) -> str:
    """Save a new summary to the summaries table (dual-write target).
    
    Returns the summary ID.
    """
    if USE_POSTGRES:
        return _save_summary_pg(summary)
    return _save_summary_sqlite(summary)


def _save_summary_sqlite(summary: Summary) -> str:
    conn = sqlite3.connect(str(DB_PATH))
    try:
        summary_id = summary.id or None
        cur = conn.execute(
            """INSERT INTO summaries
               (id, minutes_id, summary, key_decisions, budget_items,
                public_comment_opportunities, items, big_picture,
                what_you_can_do, category, neighborhood_impact, status,
                verified_by, verified_at, rejection_reason, social_posted,
                image_url, model_used)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                summary_id,
                summary.minutes_id,
                summary.summary,
                json.dumps(summary.key_decisions),
                json.dumps(summary.budget_items),
                json.dumps(summary.public_comment_opportunities),
                json.dumps(summary.items),
                summary.big_picture,
                json.dumps(summary.what_you_can_do),
                summary.category,
                summary.neighborhood_impact,
                summary.status,
                summary.verified_by,
                summary.verified_at.isoformat() if summary.verified_at else None,
                summary.rejection_reason,
                1 if summary.social_posted else 0,
                summary.image_url,
                summary.model_used,
            ),
        )
        conn.commit()
        return summary_id or cur.lastrowid
    finally:
        conn.close()


def _save_summary_pg(summary: Summary) -> str:
    conn = _get_pg_conn()
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                """INSERT INTO summaries
                   (minutes_id, summary, key_decisions, budget_items,
                    public_comment_opportunities, items, big_picture,
                    what_you_can_do, category, neighborhood_impact, status,
                    verified_by, verified_at, rejection_reason, social_posted,
                    image_url, model_used)
                   VALUES (%s, %s, %s::jsonb, %s::jsonb, %s::jsonb, %s::jsonb,
                           %s, %s::jsonb, %s, %s, %s,
                           %s, %s, %s, %s,
                           %s, %s)
                   RETURNING id""",
                (
                    summary.minutes_id,
                    summary.summary,
                    json.dumps(summary.key_decisions),
                    json.dumps(summary.budget_items),
                    json.dumps(summary.public_comment_opportunities),
                    json.dumps(summary.items),
                    summary.big_picture,
                    json.dumps(summary.what_you_can_do),
                    summary.category,
                    summary.neighborhood_impact,
                    summary.status,
                    summary.verified_by,
                    summary.verified_at.isoformat() if summary.verified_at else None,
                    summary.rejection_reason,
                    summary.social_posted,
                    summary.image_url,
                    summary.model_used,
                ),
            )
            row = cur.fetchone()
        conn.commit()
        return row["id"]
    finally:
        conn.close()


def get_summary(summary_id: str) -> Optional[Summary]:
    """Get a summary by ID."""
    if USE_POSTGRES:
        return _get_summary_pg(summary_id)
    return _get_summary_sqlite(summary_id)


def _row_to_summary(row) -> Summary:
    """Convert a DB row (dict-like) to a Summary model."""
    return Summary(
        id=str(row["id"]),
        minutes_id=str(row["minutes_id"]),
        summary=row["summary"],
        key_decisions=json.loads(row["key_decisions"]) if isinstance(row["key_decisions"], str) else (row["key_decisions"] or []),
        budget_items=json.loads(row["budget_items"]) if isinstance(row["budget_items"], str) else (row["budget_items"] or []),
        public_comment_opportunities=json.loads(row["public_comment_opportunities"]) if isinstance(row["public_comment_opportunities"], str) else (row["public_comment_opportunities"] or []),
        items=json.loads(row["items"]) if isinstance(row["items"], str) else (row["items"] or []),
        big_picture=row.get("big_picture"),
        what_you_can_do=json.loads(row["what_you_can_do"]) if isinstance(row["what_you_can_do"], str) else (row["what_you_can_do"] or []),
        category=row.get("category"),
        neighborhood_impact=row.get("neighborhood_impact"),
        status=row["status"],
        verified_by=str(row["verified_by"]) if row.get("verified_by") else None,
        verified_at=row["verified_at"] if row.get("verified_at") else None,
        rejection_reason=row.get("rejection_reason"),
        social_posted=bool(row.get("social_posted", False)),
        image_url=row.get("image_url"),
        model_used=row.get("model_used"),
    )


def _get_summary_sqlite(summary_id: str) -> Optional[Summary]:
    conn = sqlite3.connect(str(DB_PATH))
    try:
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT * FROM summaries WHERE id = ?", (summary_id,)
        ).fetchone()
        if not row:
            return None
        return _row_to_summary(row)
    finally:
        conn.close()


def _get_summary_pg(summary_id: str) -> Optional[Summary]:
    conn = _get_pg_conn()
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                "SELECT * FROM summaries WHERE id = %s", (summary_id,)
            )
            row = cur.fetchone()
            if not row:
                return None
            return _row_to_summary(row)
    finally:
        conn.close()


def list_pending_summaries() -> list[dict]:
    """List summaries with status='pending', including related minute info."""
    if USE_POSTGRES:
        return _list_pending_summaries_pg()
    return _list_pending_summaries_sqlite()


def _list_pending_summaries_sqlite() -> list[dict]:
    conn = sqlite3.connect(str(DB_PATH))
    try:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            """SELECT s.id, s.summary, s.category, s.neighborhood_impact,
                      s.status, s.created_at,
                      m.raw_text, m.meeting_date, m.title
               FROM summaries s
               JOIN minutes m ON m.id = s.minutes_id
               WHERE s.status = 'pending'
               ORDER BY s.created_at DESC"""
        ).fetchall()
        return [
            {
                "id": str(r["id"]),
                "summary": r["summary"],
                "raw_text": r["raw_text"],
                "category": r["category"],
                "neighborhood_impact": r["neighborhood_impact"],
                "meeting_date": r["meeting_date"],
                "title": r["title"],
            }
            for r in rows
        ]
    finally:
        conn.close()


def _list_pending_summaries_pg() -> list[dict]:
    conn = _get_pg_conn()
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                """SELECT s.id, s.summary, s.category, s.neighborhood_impact,
                          s.status, s.created_at,
                          m.raw_text, m.meeting_date, m.title
                   FROM summaries s
                   JOIN minutes m ON m.id = s.minutes_id
                   WHERE s.status = 'pending'
                   ORDER BY s.created_at DESC"""
            )
            rows = cur.fetchall()
            return [
                {
                    "id": str(r["id"]),
                    "summary": r["summary"],
                    "raw_text": r["raw_text"],
                    "category": r["category"],
                    "neighborhood_impact": r["neighborhood_impact"],
                    "meeting_date": r["meeting_date"],
                    "title": r["title"],
                }
                for r in rows
            ]
    finally:
        conn.close()


def update_summary_status(
    summary_id: str,
    status: str,
    verified_by: Optional[str] = None,
    verified_at: Optional[datetime] = None,
    rejection_reason: Optional[str] = None,
    edited_summary: Optional[str] = None,
) -> None:
    """Update a summary's verification status."""
    if USE_POSTGRES:
        _update_summary_status_pg(summary_id, status, verified_by, verified_at, rejection_reason, edited_summary)
    else:
        _update_summary_status_sqlite(summary_id, status, verified_by, verified_at, rejection_reason, edited_summary)


def _update_summary_status_sqlite(
    summary_id: str,
    status: str,
    verified_by: Optional[str] = None,
    verified_at: Optional[datetime] = None,
    rejection_reason: Optional[str] = None,
    edited_summary: Optional[str] = None,
) -> None:
    conn = sqlite3.connect(str(DB_PATH))
    try:
        fields = ["status = ?", "updated_at = datetime('now')"]
        params: list = [status]
        if verified_by is not None:
            fields.append("verified_by = ?")
            params.append(verified_by)
        if verified_at is not None:
            fields.append("verified_at = ?")
            params.append(verified_at.isoformat())
        if rejection_reason is not None:
            fields.append("rejection_reason = ?")
            params.append(rejection_reason)
        if edited_summary is not None:
            fields.append("summary = ?")
            params.append(edited_summary)
        params.append(summary_id)
        conn.execute(
            f"UPDATE summaries SET {', '.join(fields)} WHERE id = ?",
            params,
        )
        conn.commit()
    finally:
        conn.close()


def _update_summary_status_pg(
    summary_id: str,
    status: str,
    verified_by: Optional[str] = None,
    verified_at: Optional[datetime] = None,
    rejection_reason: Optional[str] = None,
    edited_summary: Optional[str] = None,
) -> None:
    conn = _get_pg_conn()
    try:
        with conn.cursor() as cur:
            fields = ["status = %s", "updated_at = NOW()"]
            params: list = [status]
            if verified_by is not None:
                fields.append("verified_by = %s")
                params.append(verified_by)
            if verified_at is not None:
                fields.append("verified_at = %s")
                params.append(verified_at)
            if rejection_reason is not None:
                fields.append("rejection_reason = %s")
                params.append(rejection_reason)
            if edited_summary is not None:
                fields.append("summary = %s")
                params.append(edited_summary)
            params.append(summary_id)
            cur.execute(
                f"UPDATE summaries SET {', '.join(fields)} WHERE id = %s",
                params,
            )
        conn.commit()
    finally:
        conn.close()


def update_summary_social(summary_id: str, image_url: str) -> None:
    """Update a summary's social_posted flag and image_url after pipeline success."""
    if USE_POSTGRES:
        _update_summary_social_pg(summary_id, image_url)
    else:
        _update_summary_social_sqlite(summary_id, image_url)


def _update_summary_social_sqlite(summary_id: str, image_url: str) -> None:
    conn = sqlite3.connect(str(DB_PATH))
    try:
        conn.execute(
            """UPDATE summaries
               SET social_posted = 1,
                   image_url = ?,
                   updated_at = datetime('now')
               WHERE id = ?""",
            (image_url, summary_id),
        )
        conn.commit()
    finally:
        conn.close()


def _update_summary_social_pg(summary_id: str, image_url: str) -> None:
    conn = _get_pg_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """UPDATE summaries
                   SET social_posted = TRUE,
                       image_url = %s,
                       updated_at = NOW()
                   WHERE id = %s""",
                (image_url, summary_id),
            )
        conn.commit()
    finally:
        conn.close()


# --- Volunteers CRUD ---


def save_volunteer(volunteer: Volunteer) -> None:
    """Insert a new volunteer."""
    if USE_POSTGRES:
        _save_volunteer_pg(volunteer)
    else:
        _save_volunteer_sqlite(volunteer)


def _save_volunteer_sqlite(volunteer: Volunteer) -> None:
    conn = sqlite3.connect(str(DB_PATH))
    try:
        conn.execute(
            """INSERT OR REPLACE INTO volunteers
               (user_id, email, full_name, school, hours_earned, is_active)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (
                volunteer.user_id,
                volunteer.email,
                volunteer.full_name,
                volunteer.school,
                volunteer.hours_earned,
                1 if volunteer.is_active else 0,
            ),
        )
        conn.commit()
    finally:
        conn.close()


def _save_volunteer_pg(volunteer: Volunteer) -> None:
    conn = _get_pg_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """INSERT INTO volunteers
                   (user_id, email, full_name, school, hours_earned, is_active)
                   VALUES (%s, %s, %s, %s, %s, %s)
                   ON CONFLICT (user_id) DO UPDATE SET
                       email = EXCLUDED.email,
                       full_name = EXCLUDED.full_name,
                       school = EXCLUDED.school,
                       hours_earned = EXCLUDED.hours_earned,
                       is_active = EXCLUDED.is_active,
                       updated_at = NOW()""",
                (
                    volunteer.user_id,
                    volunteer.email,
                    volunteer.full_name,
                    volunteer.school,
                    volunteer.hours_earned,
                    volunteer.is_active,
                ),
            )
        conn.commit()
    finally:
        conn.close()


def get_volunteer(user_id: str) -> Optional[Volunteer]:
    """Get a volunteer by user_id."""
    if USE_POSTGRES:
        return _get_volunteer_pg(user_id)
    return _get_volunteer_sqlite(user_id)


def _get_volunteer_sqlite(user_id: str) -> Optional[Volunteer]:
    conn = sqlite3.connect(str(DB_PATH))
    try:
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT * FROM volunteers WHERE user_id = ?", (user_id,)
        ).fetchone()
        if not row:
            return None
        return Volunteer(
            user_id=row["user_id"],
            email=row["email"],
            full_name=row["full_name"],
            school=row["school"],
            hours_earned=row["hours_earned"],
            is_active=bool(row["is_active"]),
        )
    finally:
        conn.close()


def _get_volunteer_pg(user_id: str) -> Optional[Volunteer]:
    conn = _get_pg_conn()
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                "SELECT * FROM volunteers WHERE user_id = %s", (user_id,)
            )
            row = cur.fetchone()
            if not row:
                return None
            return Volunteer(
                user_id=str(row["user_id"]),
                email=row["email"],
                full_name=row["full_name"],
                school=row["school"],
                hours_earned=float(row["hours_earned"]),
                is_active=row["is_active"],
            )
    finally:
        conn.close()


def get_volunteer_by_email(email: str) -> Optional[Volunteer]:
    """Get a volunteer by email."""
    if USE_POSTGRES:
        return _get_volunteer_by_email_pg(email)
    return _get_volunteer_by_email_sqlite(email)


def _get_volunteer_by_email_sqlite(email: str) -> Optional[Volunteer]:
    conn = sqlite3.connect(str(DB_PATH))
    try:
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT * FROM volunteers WHERE email = ?", (email,)
        ).fetchone()
        if not row:
            return None
        return Volunteer(
            user_id=row["user_id"],
            email=row["email"],
            full_name=row["full_name"],
            school=row["school"],
            hours_earned=row["hours_earned"],
            is_active=bool(row["is_active"]),
        )
    finally:
        conn.close()


def _get_volunteer_by_email_pg(email: str) -> Optional[Volunteer]:
    conn = _get_pg_conn()
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                "SELECT * FROM volunteers WHERE email = %s", (email,)
            )
            row = cur.fetchone()
            if not row:
                return None
            return Volunteer(
                user_id=str(row["user_id"]),
                email=row["email"],
                full_name=row["full_name"],
                school=row["school"],
                hours_earned=float(row["hours_earned"]),
                is_active=row["is_active"],
            )
    finally:
        conn.close()


def update_volunteer_hours(user_id: str, hours: float) -> None:
    """Add hours to a volunteer's earned total."""
    if USE_POSTGRES:
        _update_volunteer_hours_pg(user_id, hours)
    else:
        _update_volunteer_hours_sqlite(user_id, hours)


def _update_volunteer_hours_sqlite(user_id: str, hours: float) -> None:
    conn = sqlite3.connect(str(DB_PATH))
    try:
        conn.execute(
            "UPDATE volunteers SET hours_earned = hours_earned + ?, updated_at = datetime('now') WHERE user_id = ?",
            (hours, user_id),
        )
        conn.commit()
    finally:
        conn.close()


def _update_volunteer_hours_pg(user_id: str, hours: float) -> None:
    conn = _get_pg_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE volunteers SET hours_earned = hours_earned + %s, updated_at = NOW() WHERE user_id = %s",
                (hours, user_id),
            )
        conn.commit()
    finally:
        conn.close()


# --- Verification Sessions CRUD ---


def create_verification_session(volunteer_id: str, summary_id: str) -> str:
    """Create a new verification session and return its ID."""
    if USE_POSTGRES:
        return _create_verification_session_pg(volunteer_id, summary_id)
    return _create_verification_session_sqlite(volunteer_id, summary_id)


def _create_verification_session_sqlite(volunteer_id: str, summary_id: str) -> str:
    conn = sqlite3.connect(str(DB_PATH))
    try:
        cur = conn.execute(
            """INSERT INTO verification_sessions
               (volunteer_id, summary_id, started_at)
               VALUES (?, ?, datetime('now'))""",
            (volunteer_id, summary_id),
        )
        conn.commit()
        return cur.lastrowid
    finally:
        conn.close()


def _create_verification_session_pg(volunteer_id: str, summary_id: str) -> str:
    conn = _get_pg_conn()
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                """INSERT INTO verification_sessions
                   (volunteer_id, summary_id)
                   VALUES (%s, %s)
                   RETURNING id""",
                (volunteer_id, summary_id),
            )
            row = cur.fetchone()
        conn.commit()
        return row["id"]
    finally:
        conn.close()


def complete_verification_session(
    session_id: str,
    action: str,
    notes: Optional[str] = None,
) -> None:
    """Mark a verification session as completed with action and duration."""
    if USE_POSTGRES:
        _complete_verification_session_pg(session_id, action, notes)
    else:
        _complete_verification_session_sqlite(session_id, action, notes)


def _complete_verification_session_sqlite(
    session_id: str,
    action: str,
    notes: Optional[str] = None,
) -> None:
    conn = sqlite3.connect(str(DB_PATH))
    try:
        conn.execute(
            """UPDATE verification_sessions
               SET ended_at = datetime('now'),
                   duration_seconds = CAST(
                       (julianday(datetime('now')) - julianday(started_at)) * 86400 AS INTEGER
                   ),
                   action = ?,
                   notes = ?
               WHERE id = ?""",
            (action, notes, session_id),
        )
        conn.commit()
    finally:
        conn.close()


def _complete_verification_session_pg(
    session_id: str,
    action: str,
    notes: Optional[str] = None,
) -> None:
    conn = _get_pg_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """UPDATE verification_sessions
                   SET ended_at = NOW(),
                       duration_seconds = EXTRACT(EPOCH FROM (NOW() - started_at))::INTEGER,
                       action = %s,
                       notes = %s
                   WHERE id = %s""",
                (action, notes, session_id),
            )
        conn.commit()
    finally:
        conn.close()


def get_volunteer_sessions(user_id: str) -> list[dict]:
    """Get all verification sessions for a volunteer with summary info."""
    if USE_POSTGRES:
        return _get_volunteer_sessions_pg(user_id)
    return _get_volunteer_sessions_sqlite(user_id)


def _get_volunteer_sessions_sqlite(user_id: str) -> list[dict]:
    conn = sqlite3.connect(str(DB_PATH))
    try:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            """SELECT vs.id, vs.started_at, vs.ended_at, vs.duration_seconds,
                      vs.action, vs.notes,
                      s.summary, s.status, s.minutes_id
               FROM verification_sessions vs
               JOIN summaries s ON s.id = vs.summary_id
               WHERE vs.volunteer_id = ?
               ORDER BY vs.started_at DESC""",
            (user_id,),
        ).fetchall()
        return [
            {
                "id": str(r["id"]),
                "started_at": r["started_at"],
                "ended_at": r["ended_at"],
                "duration_seconds": r["duration_seconds"],
                "action": r["action"],
                "notes": r["notes"],
                "summary_preview": r["summary"][:100] if r["summary"] else "",
                "status": r["status"],
                "minutes_id": r["minutes_id"],
            }
            for r in rows
        ]
    finally:
        conn.close()


def _get_volunteer_sessions_pg(user_id: str) -> list[dict]:
    conn = _get_pg_conn()
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                """SELECT vs.id, vs.started_at, vs.ended_at, vs.duration_seconds,
                          vs.action, vs.notes,
                          s.summary, s.status, s.minutes_id
                   FROM verification_sessions vs
                   JOIN summaries s ON s.id = vs.summary_id
                   WHERE vs.volunteer_id = %s
                   ORDER BY vs.started_at DESC""",
                (user_id,),
            )
            rows = cur.fetchall()
            return [
                {
                    "id": str(r["id"]),
                    "started_at": r["started_at"].isoformat() if r["started_at"] else None,
                    "ended_at": r["ended_at"].isoformat() if r["ended_at"] else None,
                    "duration_seconds": r["duration_seconds"],
                    "action": r["action"],
                    "notes": r["notes"],
                    "summary_preview": r["summary"][:100] if r["summary"] else "",
                    "status": r["status"],
                    "minutes_id": r["minutes_id"],
                }
                for r in rows
            ]
    finally:
        conn.close()


# --- Dual-Write: When saving a summary, write to both tables ---


def save_minutes_summary_dual(minutes_id: str, summary: SummaryResponse) -> str:
    """Save to both minutes_summaries (existing) and summaries (new table).
    
    This implements the dual-write approach: the existing code path continues
    to write to minutes_summaries, and we also write to the new summaries table
    with status='pending' for volunteer verification.
    """
    # Write to existing table (unchanged behavior)
    save_minutes_summary(minutes_id, summary)

    # Write to new summaries table
    new_summary = Summary(
        minutes_id=minutes_id,
        summary=summary.summary,
        key_decisions=summary.key_decisions,
        budget_items=summary.budget_items,
        public_comment_opportunities=summary.public_comment_opportunities,
        items=summary.items,
        big_picture=summary.big_picture,
        what_you_can_do=summary.what_you_can_do,
        status="pending",
    )
    return save_summary(new_summary)


# --- Backfill: Copy existing minutes_summaries into summaries table ---


def backfill_summaries() -> dict:
    """Copy all existing minutes_summaries rows into the new summaries table.
    
    Returns a dict with counts of how many were backfilled.
    """
    if USE_POSTGRES:
        return _backfill_summaries_pg()
    return _backfill_summaries_sqlite()


def _backfill_summaries_sqlite() -> dict:
    conn = sqlite3.connect(str(DB_PATH))
    try:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            """SELECT ms.*, m.raw_text
               FROM minutes_summaries ms
               LEFT JOIN minutes m ON m.id = ms.minutes_id"""
        ).fetchall()

        backfilled = 0
        skipped = 0
        for row in rows:
            # Check if already exists
            existing = conn.execute(
                "SELECT 1 FROM summaries WHERE minutes_id = ?", (row["minutes_id"],)
            ).fetchone()
            if existing:
                skipped += 1
                continue

            conn.execute(
                """INSERT INTO summaries
                   (minutes_id, summary, key_decisions, budget_items,
                    public_comment_opportunities, items, big_picture,
                    what_you_can_do, status, model_used)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'pending', ?)""",
                (
                    row["minutes_id"],
                    row["summary"],
                    row["key_decisions"],
                    row["budget_items"],
                    row["public_comment_opportunities"],
                    row["items"],
                    row["big_picture"],
                    row["what_you_can_do"],
                    row["model_used"],
                ),
            )
            backfilled += 1

        conn.commit()
        return {"backfilled": backfilled, "skipped": skipped, "total": len(rows)}
    finally:
        conn.close()


def _backfill_summaries_pg() -> dict:
    conn = _get_pg_conn()
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                """SELECT ms.*, m.raw_text
                   FROM minutes_summaries ms
                   LEFT JOIN minutes m ON m.id = ms.minutes_id"""
            )
            rows = cur.fetchall()

        backfilled = 0
        skipped = 0
        for row in rows:
            with conn.cursor() as icur:
                icur.execute(
                    "SELECT 1 FROM summaries WHERE minutes_id = %s", (row["minutes_id"],)
                )
                if icur.fetchone():
                    skipped += 1
                    continue

                icur.execute(
                    """INSERT INTO summaries
                       (minutes_id, summary, key_decisions, budget_items,
                        public_comment_opportunities, items, big_picture,
                        what_you_can_do, status, model_used)
                       VALUES (%s, %s, %s::jsonb, %s::jsonb, %s::jsonb, %s::jsonb,
                               %s, %s::jsonb, 'pending', %s)""",
                    (
                        row["minutes_id"],
                        row["summary"],
                        row["key_decisions"],
                        row["budget_items"],
                        row["public_comment_opportunities"],
                        row["items"],
                        row["big_picture"],
                        row["what_you_can_do"],
                        row["model_used"],
                    ),
                )
                backfilled += 1

        conn.commit()
        return {"backfilled": backfilled, "skipped": skipped, "total": len(rows)}
    finally:
        conn.close()


def _minutes_summary_exists_pg(minutes_id: str) -> bool:
    """Check minutes summary existence in PostgreSQL."""
    conn = _get_pg_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT 1 FROM minutes_summaries WHERE minutes_id = %s", (minutes_id,)
            )
            return cur.fetchone() is not None
    finally:
        conn.close()
