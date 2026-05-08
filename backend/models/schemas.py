"""Core data models for Civic City Hub."""

from datetime import datetime, timezone
from typing import Optional
from pydantic import BaseModel, Field


class AgendaItem(BaseModel):
    """A single item on a city council agenda."""
    title: str
    description: Optional[str] = None
    category: Optional[str] = None  # e.g. "Public Hearing", "Consent Agenda", "New Business"
    department: Optional[str] = None
    staff_contact: Optional[str] = None
    attachments: list[str] = Field(default_factory=list)
    plain_language_summary: Optional[str] = None
    budget_impact: Optional[str] = None
    vote_result: Optional[str] = None  # "Passed", "Failed", "Tabled", etc.


class Agenda(BaseModel):
    """A complete city council meeting agenda."""
    id: str
    city: str = "Paris"
    state: str = "TX"
    meeting_date: datetime
    meeting_type: str = "City Council Regular Meeting"
    title: str
    url: str
    pdf_url: Optional[str] = None
    document_url: Optional[str] = None
    items: list[AgendaItem] = Field(default_factory=list)
    raw_text: Optional[str] = None
    summary: Optional[str] = None
    source: str = "civicplus"  # connector type used
    ingested_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class Minutes(BaseModel):
    """A city council meeting minutes document (the official record of what happened)."""
    id: str
    city: str = "Paris"
    state: str = "TX"
    meeting_date: datetime
    meeting_type: str = "City Council Meeting"
    title: str
    url: str
    document_url: Optional[str] = None
    raw_text: Optional[str] = None
    summary: Optional[str] = None
    source: str = "laserfiche"
    ingested_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class CityConfig(BaseModel):
    """Configuration for a connected city."""
    name: str
    state: str
    website_url: str
    agenda_center_url: str
    connector_type: str = "civicplus"  # civicplus, granicus, legistar, laserfiche, rss
    laserfiche_url: Optional[str] = None
    rss_feed_url: Optional[str] = None
    active: bool = True
    last_sync: Optional[datetime] = None


class SummaryRequest(BaseModel):
    """Request to summarize an agenda."""
    agenda_id: str
    model: str = "gpt-4o-mini"
    include_budget_analysis: bool = False


class SummaryResponse(BaseModel):
    """Response with plain-language summary."""
    agenda_id: str
    meeting_date: datetime
    meeting_type: str
    summary: str
    key_decisions: list[dict] = Field(default_factory=list)
    budget_items: list[dict] = Field(default_factory=list)
    public_comment_opportunities: list[dict] = Field(default_factory=list)
    items: list[dict] = Field(default_factory=list)
