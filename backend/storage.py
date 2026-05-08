"""
Persistent SQLite storage for Civic City Hub.

Stores agendas and summaries in a local SQLite database.
Zero infrastructure cost — just a file on disk.
Works everywhere: local dev, Vercel, Railway, Render, etc.

For Vercel free tier: SQLite works in serverless functions
(read-only on ephemeral filesystem, but fine for caching).
For true persistence on Vercel free tier, upgrade to Vercel Postgres
or Vercel KV (both have generous free tiers).
"""

import json
import os
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Optional

from models.schemas import Agenda, SummaryResponse

# Database path — stored alongside the backend code
DB_DIR = Path(__file__).parent / "data"
DB_PATH = DB_DIR / "civic_city_hub.db"


def _get_db() -> sqlite3.Connection:
    """Get a SQLite connection with row factory enabled."""
    DB_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")  # Better concurrent access
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db():
    """Initialize the database schema."""
    conn = _get_db()
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


# --- Agenda Storage ---


def save_agenda(agenda: Agenda) -> None:
    """Save or update an agenda in the database."""
    conn = _get_db()
    try:
        conn.execute(
            """INSERT OR REPLACE INTO agendas
               (id, city, state, meeting_date, meeting_type, title, url,
                pdf_url, document_url, raw_text, summary, source, ingested_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                agenda.id,
                agenda.city,
                agenda.state,
                agenda.meeting_date.isoformat(),
                agenda.meeting_type,
                agenda.title,
                agenda.url,
                agenda.pdf_url,
                agenda.document_url,
                agenda.raw_text,
                agenda.summary,
                agenda.source,
                agenda.ingested_at.isoformat(),
            ),
        )
        # Save agenda items
        conn.execute("DELETE FROM agenda_items WHERE agenda_id = ?", (agenda.id,))
        for item in agenda.items:
            conn.execute(
                """INSERT INTO agenda_items
                   (agenda_id, title, description, category, department,
                    staff_contact, attachments, plain_language_summary,
                    budget_impact, vote_result)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    agenda.id,
                    item.title,
                    item.description,
                    item.category,
                    item.department,
                    item.staff_contact,
                    json.dumps(item.attachments),
                    item.plain_language_summary,
                    item.budget_impact,
                    item.vote_result,
                ),
            )
        conn.commit()
    finally:
        conn.close()


def get_agenda(agenda_id: str) -> Optional[Agenda]:
    """Retrieve an agenda by ID."""
    conn = _get_db()
    try:
        row = conn.execute(
            "SELECT * FROM agendas WHERE id = ?", (agenda_id,)
        ).fetchone()
        if not row:
            return None

        items_rows = conn.execute(
            "SELECT * FROM agenda_items WHERE agenda_id = ? ORDER BY id",
            (agenda_id,),
        ).fetchall()

        from models.schemas import AgendaItem

        items = []
        for ir in items_rows:
            items.append(AgendaItem(
                title=ir["title"],
                description=ir["description"],
                category=ir["category"],
                department=ir["department"],
                staff_contact=ir["staff_contact"],
                attachments=json.loads(ir["attachments"]) if ir["attachments"] else [],
                plain_language_summary=ir["plain_language_summary"],
                budget_impact=ir["budget_impact"],
                vote_result=ir["vote_result"],
            ))

        return Agenda(
            id=row["id"],
            city=row["city"],
            state=row["state"],
            meeting_date=datetime.fromisoformat(row["meeting_date"]),
            meeting_type=row["meeting_type"],
            title=row["title"],
            url=row["url"],
            pdf_url=row["pdf_url"],
            document_url=row["document_url"],
            raw_text=row["raw_text"],
            summary=row["summary"],
            source=row["source"],
            ingested_at=datetime.fromisoformat(row["ingested_at"]),
            items=items,
        )
    finally:
        conn.close()


def list_agendas(limit: int = 10) -> list[dict]:
    """List recent agendas with summary status."""
    conn = _get_db()
    try:
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


# --- Summary Storage ---


def save_summary(summary: SummaryResponse) -> None:
    """Save or update a summary in the database."""
    conn = _get_db()
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


def get_summary(agenda_id: str) -> Optional[SummaryResponse]:
    """Retrieve a summary by agenda ID."""
    conn = _get_db()
    try:
        row = conn.execute(
            "SELECT * FROM summaries WHERE agenda_id = ?", (agenda_id,)
        ).fetchone()
        if not row:
            return None
        return SummaryResponse(
            agenda_id=row["agenda_id"],
            meeting_date=datetime.fromisoformat(row["meeting_date"]),
            meeting_type=row["meeting_type"],
            summary=row["summary"],
            key_decisions=json.loads(row["key_decisions"]),
            budget_items=json.loads(row["budget_items"]),
            public_comment_opportunities=json.loads(row["public_comment_opportunities"]),
            items=json.loads(row["items"]),
        )
    finally:
        conn.close()


def list_summaries() -> dict[str, dict]:
    """List all saved summaries (lightweight, no full content)."""
    conn = _get_db()
    try:
        rows = conn.execute(
            """SELECT agenda_id, meeting_date, meeting_type,
                      substr(summary, 1, 200) as summary_preview,
                      json_array_length(key_decisions) as key_decisions_count,
                      json_array_length(budget_items) as budget_items_count
               FROM summaries
               ORDER BY meeting_date DESC""",
        ).fetchall()
        result = {}
        for r in rows:
            preview = r["summary_preview"]
            if len(preview) >= 200:
                preview += "..."
            result[r["agenda_id"]] = {
                "agenda_id": r["agenda_id"],
                "meeting_date": r["meeting_date"],
                "meeting_type": r["meeting_type"],
                "summary": preview,
                "key_decisions_count": r["key_decisions_count"] or 0,
                "budget_items_count": r["budget_items_count"] or 0,
            }
        return result
    finally:
        conn.close()


def summary_exists(agenda_id: str) -> bool:
    """Check if a summary already exists for this agenda."""
    conn = _get_db()
    try:
        row = conn.execute(
            "SELECT 1 FROM summaries WHERE agenda_id = ?", (agenda_id,)
        ).fetchone()
        return row is not None
    finally:
        conn.close()
