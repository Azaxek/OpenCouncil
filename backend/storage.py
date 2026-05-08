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
from datetime import datetime
from pathlib import Path
from typing import Optional

from models.schemas import Agenda, SummaryResponse

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
    """Initialize SQLite schema."""
    DB_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH))
    try:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS agendas (
                id TEXT PRIMARY KEY,
                city TEXT NOT NULL DEFAULT 'Paris',
                state TEXT NOT NULL DEFAULT 'TX',
                meeting_date TEXT NOT NULL,
                meeting_type TEXT NOT NULL DEFAULT 'City Council Regular Meeting',
                title TEXT NOT NULL,
                url TEXT NOT NULL DEFAULT '',
                pdf_url TEXT,
                document_url TEXT,
                raw_text TEXT,
                summary TEXT,
                source TEXT DEFAULT 'civicplus',
                ingested_at TEXT NOT NULL DEFAULT (datetime('now')),
                created_at TEXT NOT NULL DEFAULT (datetime('now')),
                updated_at TEXT NOT NULL DEFAULT (datetime('now'))
            );

            CREATE TABLE IF NOT EXISTS agenda_items (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                agenda_id TEXT NOT NULL,
                title TEXT NOT NULL,
                description TEXT,
                category TEXT,
                department TEXT,
                staff_contact TEXT,
                attachments TEXT DEFAULT '[]',
                plain_language_summary TEXT,
                budget_impact TEXT,
                vote_result TEXT,
                FOREIGN KEY (agenda_id) REFERENCES agendas(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS summaries (
                agenda_id TEXT PRIMARY KEY,
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
                FOREIGN KEY (agenda_id) REFERENCES agendas(id) ON DELETE CASCADE
            );

            CREATE INDEX IF NOT EXISTS idx_agendas_date ON agendas(meeting_date DESC);
            CREATE INDEX IF NOT EXISTS idx_agendas_city ON agendas(city, state);
            CREATE INDEX IF NOT EXISTS idx_summaries_date ON summaries(meeting_date DESC);
        """)
        conn.commit()
    finally:
        conn.close()


def _init_pg():
    """Initialize PostgreSQL schema."""
    conn = _get_pg_conn()
    try:
        with conn.cursor() as cur:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS agendas (
                    id TEXT PRIMARY KEY,
                    city TEXT NOT NULL DEFAULT 'Paris',
                    state TEXT NOT NULL DEFAULT 'TX',
                    meeting_date TEXT NOT NULL,
                    meeting_type TEXT NOT NULL DEFAULT 'City Council Regular Meeting',
                    title TEXT NOT NULL,
                    url TEXT NOT NULL DEFAULT '',
                    pdf_url TEXT,
                    document_url TEXT,
                    raw_text TEXT,
                    summary TEXT,
                    source TEXT DEFAULT 'civicplus',
                    ingested_at TIMESTAMP NOT NULL DEFAULT NOW(),
                    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
                    updated_at TIMESTAMP NOT NULL DEFAULT NOW()
                );
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS agenda_items (
                    id SERIAL PRIMARY KEY,
                    agenda_id TEXT NOT NULL REFERENCES agendas(id) ON DELETE CASCADE,
                    title TEXT NOT NULL,
                    description TEXT,
                    category TEXT,
                    department TEXT,
                    staff_contact TEXT,
                    attachments TEXT DEFAULT '[]',
                    plain_language_summary TEXT,
                    budget_impact TEXT,
                    vote_result TEXT
                );
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS summaries (
                    agenda_id TEXT PRIMARY KEY REFERENCES agendas(id) ON DELETE CASCADE,
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
            # Create indexes (IF NOT EXISTS for indexes requires PG 9.5+)
            cur.execute("""
                CREATE INDEX IF NOT EXISTS idx_agendas_date ON agendas(meeting_date DESC);
            """)
            cur.execute("""
                CREATE INDEX IF NOT EXISTS idx_agendas_city ON agendas(city, state);
            """)
            cur.execute("""
                CREATE INDEX IF NOT EXISTS idx_summaries_date ON summaries(meeting_date DESC);
            """)
        conn.commit()
    finally:
        conn.close()


# --- Agenda Storage ---


def save_agenda(agenda: Agenda) -> None:
    """Save or update an agenda in the database."""
    if USE_POSTGRES:
        _save_agenda_pg(agenda)
    else:
        _save_agenda_sqlite(agenda)


def _save_agenda_sqlite(agenda: Agenda) -> None:
    """Save agenda to SQLite."""
    conn = sqlite3.connect(str(DB_PATH))
    try:
        conn.execute(
            """INSERT OR REPLACE INTO agendas
               (id, city, state, meeting_date, meeting_type, title, url,
                pdf_url, document_url, raw_text, summary, source, ingested_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                agenda.id, agenda.city, agenda.state,
                agenda.meeting_date.isoformat(), agenda.meeting_type,
                agenda.title, agenda.url, agenda.pdf_url, agenda.document_url,
                agenda.raw_text, agenda.summary, agenda.source,
                agenda.ingested_at.isoformat(),
            ),
        )
        conn.execute("DELETE FROM agenda_items WHERE agenda_id = ?", (agenda.id,))
        for item in agenda.items:
            conn.execute(
                """INSERT INTO agenda_items
                   (agenda_id, title, description, category, department,
                    staff_contact, attachments, plain_language_summary,
                    budget_impact, vote_result)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    agenda.id, item.title, item.description, item.category,
                    item.department, item.staff_contact,
                    json.dumps(item.attachments),
                    item.plain_language_summary, item.budget_impact, item.vote_result,
                ),
            )
        conn.commit()
    finally:
        conn.close()


def _save_agenda_pg(agenda: Agenda) -> None:
    """Save agenda to PostgreSQL."""
    conn = _get_pg_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """INSERT INTO agendas
                   (id, city, state, meeting_date, meeting_type, title, url,
                    pdf_url, document_url, raw_text, summary, source, ingested_at)
                   VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                   ON CONFLICT (id) DO UPDATE SET
                   city=EXCLUDED.city, state=EXCLUDED.state,
                   meeting_date=EXCLUDED.meeting_date, meeting_type=EXCLUDED.meeting_type,
                   title=EXCLUDED.title, url=EXCLUDED.url,
                   pdf_url=EXCLUDED.pdf_url, document_url=EXCLUDED.document_url,
                   raw_text=EXCLUDED.raw_text, summary=EXCLUDED.summary,
                   source=EXCLUDED.source, updated_at=NOW()""",
                (
                    agenda.id, agenda.city, agenda.state,
                    agenda.meeting_date.isoformat(), agenda.meeting_type,
                    agenda.title, agenda.url, agenda.pdf_url, agenda.document_url,
                    agenda.raw_text, agenda.summary, agenda.source,
                    agenda.ingested_at.isoformat(),
                ),
            )
            # Replace agenda items
            cur.execute("DELETE FROM agenda_items WHERE agenda_id = %s", (agenda.id,))
            for item in agenda.items:
                cur.execute(
                    """INSERT INTO agenda_items
                       (agenda_id, title, description, category, department,
                        staff_contact, attachments, plain_language_summary,
                        budget_impact, vote_result)
                       VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
                    (
                        agenda.id, item.title, item.description, item.category,
                        item.department, item.staff_contact,
                        json.dumps(item.attachments),
                        item.plain_language_summary, item.budget_impact, item.vote_result,
                    ),
                )
        conn.commit()
    finally:
        conn.close()


def get_agenda(agenda_id: str) -> Optional[Agenda]:
    """Retrieve an agenda by ID."""
    if USE_POSTGRES:
        return _get_agenda_pg(agenda_id)
    return _get_agenda_sqlite(agenda_id)


def _get_agenda_sqlite(agenda_id: str) -> Optional[Agenda]:
    """Get agenda from SQLite."""
    conn = sqlite3.connect(str(DB_PATH))
    try:
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT * FROM agendas WHERE id = ?", (agenda_id,)
        ).fetchone()
        if not row:
            return None
        items_rows = conn.execute(
            "SELECT * FROM agenda_items WHERE agenda_id = ? ORDER BY id",
            (agenda_id,),
        ).fetchall()
        return _row_to_agenda(row, items_rows)
    finally:
        conn.close()


def _get_agenda_pg(agenda_id: str) -> Optional[Agenda]:
    """Get agenda from PostgreSQL."""
    conn = _get_pg_conn()
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute("SELECT * FROM agendas WHERE id = %s", (agenda_id,))
            row = cur.fetchone()
            if not row:
                return None
            cur.execute(
                "SELECT * FROM agenda_items WHERE agenda_id = %s ORDER BY id",
                (agenda_id,),
            )
            items_rows = cur.fetchall()
            return _row_to_agenda(row, items_rows)
    finally:
        conn.close()


def _row_to_agenda(row, items_rows) -> Agenda:
    """Convert a database row to an Agenda model."""
    from models.schemas import AgendaItem

    items = []
    for ir in items_rows:
        items.append(AgendaItem(
            title=ir["title"],
            description=ir["description"],
            category=ir["category"],
            department=ir["department"],
            staff_contact=ir["staff_contact"],
            attachments=json.loads(ir["attachments"]) if ir.get("attachments") else [],
            plain_language_summary=ir["plain_language_summary"],
            budget_impact=ir["budget_impact"],
            vote_result=ir["vote_result"],
        ))

    return Agenda(
        id=row["id"],
        city=row["city"],
        state=row["state"],
        meeting_date=datetime.fromisoformat(row["meeting_date"]) if isinstance(row["meeting_date"], str) else row["meeting_date"],
        meeting_type=row["meeting_type"],
        title=row["title"],
        url=row["url"],
        pdf_url=row["pdf_url"],
        document_url=row["document_url"],
        raw_text=row["raw_text"],
        summary=row["summary"],
        source=row["source"],
        ingested_at=datetime.fromisoformat(row["ingested_at"]) if isinstance(row["ingested_at"], str) else row["ingested_at"],
        items=items,
    )


def list_agendas(limit: int = 10) -> list[dict]:
    """List recent agendas with summary status."""
    if USE_POSTGRES:
        return _list_agendas_pg(limit)
    return _list_agendas_sqlite(limit)


def _list_agendas_sqlite(limit: int = 10) -> list[dict]:
    """List agendas from SQLite."""
    conn = sqlite3.connect(str(DB_PATH))
    try:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            """SELECT a.id, a.title, a.meeting_date, a.meeting_type,
                      a.city, a.state, a.url,
                      CASE WHEN s.agenda_id IS NOT NULL THEN 1 ELSE 0 END as has_summary
               FROM agendas a
               LEFT JOIN summaries s ON a.id = s.agenda_id
               ORDER BY a.meeting_date DESC
               LIMIT ?""",
            (limit,),
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def _list_agendas_pg(limit: int = 10) -> list[dict]:
    """List agendas from PostgreSQL."""
    conn = _get_pg_conn()
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                """SELECT a.id, a.title, a.meeting_date, a.meeting_type,
                          a.city, a.state, a.url,
                          CASE WHEN s.agenda_id IS NOT NULL THEN 1 ELSE 0 END as has_summary
                   FROM agendas a
                   LEFT JOIN summaries s ON a.id = s.agenda_id
                   ORDER BY a.meeting_date DESC
                   LIMIT %s""",
                (limit,),
            )
            rows = cur.fetchall()
            return [dict(r) for r in rows]
    finally:
        conn.close()


# --- Summary Storage ---


def save_summary(summary: SummaryResponse) -> None:
    """Save or update a summary in the database."""
    if USE_POSTGRES:
        _save_summary_pg(summary)
    else:
        _save_summary_sqlite(summary)


def _save_summary_sqlite(summary: SummaryResponse) -> None:
    """Save summary to SQLite."""
    conn = sqlite3.connect(str(DB_PATH))
    try:
        conn.execute(
            """INSERT OR REPLACE INTO summaries
               (agenda_id, meeting_date, meeting_type, summary,
                key_decisions, budget_items, public_comment_opportunities,
                items, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))""",
            (
                summary.agenda_id,
                summary.meeting_date.isoformat(),
                summary.meeting_type,
                summary.summary,
                json.dumps(summary.key_decisions),
                json.dumps(summary.budget_items),
                json.dumps(summary.public_comment_opportunities),
                json.dumps(summary.items),
            ),
        )
        conn.commit()
    finally:
        conn.close()


def _save_summary_pg(summary: SummaryResponse) -> None:
    """Save summary to PostgreSQL."""
    conn = _get_pg_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """INSERT INTO summaries
                   (agenda_id, meeting_date, meeting_type, summary,
                    key_decisions, budget_items, public_comment_opportunities,
                    items, updated_at)
                   VALUES (%s, %s, %s, %s, %s, %s, %s, %s, NOW())
                   ON CONFLICT (agenda_id) DO UPDATE SET
                   meeting_date=EXCLUDED.meeting_date,
                   meeting_type=EXCLUDED.meeting_type,
                   summary=EXCLUDED.summary,
                   key_decisions=EXCLUDED.key_decisions,
                   budget_items=EXCLUDED.budget_items,
                   public_comment_opportunities=EXCLUDED.public_comment_opportunities,
                   items=EXCLUDED.items,
                   updated_at=NOW()""",
                (
                    summary.agenda_id,
                    summary.meeting_date.isoformat(),
                    summary.meeting_type,
                    summary.summary,
                    json.dumps(summary.key_decisions),
                    json.dumps(summary.budget_items),
                    json.dumps(summary.public_comment_opportunities),
                    json.dumps(summary.items),
                ),
            )
        conn.commit()
    finally:
        conn.close()


def get_summary(agenda_id: str) -> Optional[SummaryResponse]:
    """Retrieve a summary by agenda ID."""
    if USE_POSTGRES:
        return _get_summary_pg(agenda_id)
    return _get_summary_sqlite(agenda_id)


def _get_summary_sqlite(agenda_id: str) -> Optional[SummaryResponse]:
    """Get summary from SQLite."""
    conn = sqlite3.connect(str(DB_PATH))
    try:
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT * FROM summaries WHERE agenda_id = ?", (agenda_id,)
        ).fetchone()
        if not row:
            return None
        return _row_to_summary(row)
    finally:
        conn.close()


def _get_summary_pg(agenda_id: str) -> Optional[SummaryResponse]:
    """Get summary from PostgreSQL."""
    conn = _get_pg_conn()
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute("SELECT * FROM summaries WHERE agenda_id = %s", (agenda_id,))
            row = cur.fetchone()
            if not row:
                return None
            return _row_to_summary(row)
    finally:
        conn.close()


def _row_to_summary(row) -> SummaryResponse:
    """Convert a database row to a SummaryResponse model."""
    return SummaryResponse(
        agenda_id=row["agenda_id"],
        meeting_date=datetime.fromisoformat(row["meeting_date"]) if isinstance(row["meeting_date"], str) else row["meeting_date"],
        meeting_type=row["meeting_type"],
        summary=row["summary"],
        key_decisions=json.loads(row["key_decisions"]),
        budget_items=json.loads(row["budget_items"]),
        public_comment_opportunities=json.loads(row["public_comment_opportunities"]),
        items=json.loads(row["items"]),
    )


def list_summaries() -> dict[str, dict]:
    """List all saved summaries (lightweight, no full content)."""
    if USE_POSTGRES:
        return _list_summaries_pg()
    return _list_summaries_sqlite()


def _list_summaries_sqlite() -> dict[str, dict]:
    """List summaries from SQLite."""
    conn = sqlite3.connect(str(DB_PATH))
    try:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            """SELECT agenda_id, meeting_date, meeting_type,
                      substr(summary, 1, 200) as summary_preview,
                      json_array_length(key_decisions) as key_decisions_count,
                      json_array_length(budget_items) as budget_items_count
               FROM summaries
               ORDER BY meeting_date DESC""",
        ).fetchall()
        return _format_summary_list(rows)
    finally:
        conn.close()


def _list_summaries_pg() -> dict[str, dict]:
    """List summaries from PostgreSQL."""
    conn = _get_pg_conn()
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                """SELECT agenda_id, meeting_date, meeting_type,
                          LEFT(summary, 200) as summary_preview
                   FROM summaries
                   ORDER BY meeting_date DESC""",
            )
            rows = cur.fetchall()
            return _format_summary_list(rows)
    finally:
        conn.close()


def _format_summary_list(rows) -> dict[str, dict]:
    """Format summary list rows into the expected dict format."""
    result = {}
    for r in rows:
        preview = r["summary_preview"] or ""
        if len(preview) >= 200:
            preview += "..."
        result[r["agenda_id"]] = {
            "agenda_id": r["agenda_id"],
            "meeting_date": r["meeting_date"],
            "meeting_type": r["meeting_type"],
            "summary": preview,
            "key_decisions_count": 0,
            "budget_items_count": 0,
        }
    return result


def summary_exists(agenda_id: str) -> bool:
    """Check if a summary already exists for this agenda."""
    if USE_POSTGRES:
        return _summary_exists_pg(agenda_id)
    return _summary_exists_sqlite(agenda_id)


def _summary_exists_sqlite(agenda_id: str) -> bool:
    """Check summary existence in SQLite."""
    conn = sqlite3.connect(str(DB_PATH))
    try:
        row = conn.execute(
            "SELECT 1 FROM summaries WHERE agenda_id = ?", (agenda_id,)
        ).fetchone()
        return row is not None
    finally:
        conn.close()


def _summary_exists_pg(agenda_id: str) -> bool:
    """Check summary existence in PostgreSQL."""
    conn = _get_pg_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT 1 FROM summaries WHERE agenda_id = %s", (agenda_id,)
            )
            return cur.fetchone() is not None
    finally:
        conn.close()
