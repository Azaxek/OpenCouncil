"""
Persistent storage for Civic City Hub.

Supports two backends:
  - SQLite (local development) — zero infrastructure, file-based
  - PostgreSQL (Supabase/HF Spaces) — persistent, scalable

Switch via DATABASE_URL env var:
  - If DATABASE_URL is set → use PostgreSQL
  - Otherwise → use SQLite (local data/ directory)
"""

import json
import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from models.schemas import Minutes, SummaryResponse

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

if USE_POSTGRES:
    import psycopg2
    import psycopg2.extras
    from urllib.parse import urlparse, unquote

    def _get_pg_conn():
        """Get a PostgreSQL connection.

        Parses DATABASE_URL manually to handle special characters in passwords
        (e.g. Supabase Transaction Pooler connection strings with `]`, `@`, etc.).
        """
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
else:
    # SQLite paths
    if os.getenv("VERCEL"):
        DB_DIR = Path("/tmp/civic_city_hub_data")
    else:
        DB_DIR = Path(__file__).parent / "data"
    DB_PATH = DB_DIR / "civic_city_hub.db"


# --- Initialization ---


def init_db():
    """Initialize the database schema."""
    if USE_POSTGRES:
        _init_pg()
    else:
        _init_sqlite()


def _init_sqlite():
    """Initialize SQLite schema — minutes only."""
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
                model_used TEXT NOT NULL DEFAULT 'deepseek-chat',
                created_at TEXT NOT NULL DEFAULT (datetime('now')),
                updated_at TEXT NOT NULL DEFAULT (datetime('now')),
                FOREIGN KEY (minutes_id) REFERENCES minutes(id) ON DELETE CASCADE
            );

            CREATE INDEX IF NOT EXISTS idx_minutes_date ON minutes(meeting_date DESC);
            CREATE INDEX IF NOT EXISTS idx_minutes_city ON minutes(city, state);
        """)
        conn.commit()
    finally:
        conn.close()


def _init_pg():
    """Initialize PostgreSQL schema — minutes only."""
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
                    model_used TEXT NOT NULL DEFAULT 'deepseek-chat',
                    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
                    updated_at TIMESTAMP NOT NULL DEFAULT NOW()
                );
            """)
            cur.execute("""
                CREATE INDEX IF NOT EXISTS idx_minutes_date ON minutes(meeting_date DESC);
            """)
            cur.execute("""
                CREATE INDEX IF NOT EXISTS idx_minutes_city ON minutes(city, state);
            """)
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
                key_decisions, budget_items, public_comment_opportunities, items)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                minutes_id,
                summary.meeting_date.isoformat(),
                summary.meeting_type,
                summary.summary,
                json.dumps([k.model_dump() if hasattr(k, 'model_dump') else k for k in summary.key_decisions]),
                json.dumps([b.model_dump() if hasattr(b, 'model_dump') else b for b in summary.budget_items]),
                json.dumps([p.model_dump() if hasattr(p, 'model_dump') else p for p in summary.public_comment_opportunities]),
                json.dumps([i.model_dump() if hasattr(i, 'model_dump') else i for i in summary.items]),
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
                    key_decisions, budget_items, public_comment_opportunities, items)
                   VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                   ON CONFLICT (minutes_id) DO UPDATE SET
                       meeting_date = EXCLUDED.meeting_date,
                       meeting_type = EXCLUDED.meeting_type,
                       summary = EXCLUDED.summary,
                       key_decisions = EXCLUDED.key_decisions,
                       budget_items = EXCLUDED.budget_items,
                       public_comment_opportunities = EXCLUDED.public_comment_opportunities,
                       items = EXCLUDED.items,
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
