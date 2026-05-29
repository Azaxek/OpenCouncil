"""Core data models for OpenCouncil."""

from datetime import datetime, timezone
from typing import Optional
from pydantic import BaseModel, Field


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
    page_image_urls: list[str] = Field(default_factory=list)
    summary: Optional[str] = None
    source: str = "laserfiche"
    ingested_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class CityConfig(BaseModel):
    """Configuration for a connected city."""
    name: str
    state: str
    website_url: str
    agenda_center_url: str
    connector_type: str = "laserfiche"
    laserfiche_url: Optional[str] = None
    rss_feed_url: Optional[str] = None
    active: bool = True
    last_sync: Optional[datetime] = None


class SummaryRequest(BaseModel):
    """Request to summarize minutes."""
    minutes_id: str
    model: str = "gpt-4o-mini"
    include_budget_analysis: bool = False


class SummaryResponse(BaseModel):
    """Response with plain-language summary."""
    minutes_id: str
    meeting_date: datetime
    meeting_type: str
    big_picture: str = ""
    summary: str
    key_decisions: list[dict] = Field(default_factory=list)
    budget_items: list[dict] = Field(default_factory=list)
    public_comment_opportunities: list[dict] = Field(default_factory=list)
    items: list[dict] = Field(default_factory=list)
    what_you_can_do: list[dict] = Field(default_factory=list)


# --- New Models for Phases 1-4 ---


class Volunteer(BaseModel):
    """A volunteer who verifies summaries."""
    user_id: str
    email: str
    full_name: str
    school: Optional[str] = None
    hours_earned: float = 0.00
    is_active: bool = True
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class Summary(BaseModel):
    """A plain-language summary stored in the new summaries table."""
    id: str = ""
    minutes_id: str
    summary: str
    key_decisions: list[dict] = Field(default_factory=list)
    budget_items: list[dict] = Field(default_factory=list)
    public_comment_opportunities: list[dict] = Field(default_factory=list)
    items: list[dict] = Field(default_factory=list)
    big_picture: Optional[str] = None
    what_you_can_do: list[dict] = Field(default_factory=list)
    category: Optional[str] = None
    neighborhood_impact: Optional[str] = None
    status: str = "pending"
    verified_by: Optional[str] = None
    verified_at: Optional[datetime] = None
    rejection_reason: Optional[str] = None
    social_posted: bool = False
    image_url: Optional[str] = None
    model_used: Optional[str] = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class VerificationSession(BaseModel):
    """A verification session tracking volunteer review of a summary."""
    id: str = ""
    volunteer_id: str
    summary_id: str
    started_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    ended_at: Optional[datetime] = None
    duration_seconds: Optional[int] = None
    action: Optional[str] = None
    notes: Optional[str] = None
