"""Core data models for Civic City Hub."""

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
