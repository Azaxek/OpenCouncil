"""
Verification endpoints for OpenCouncil.

All endpoints require JWT authentication via Supabase Auth.
Volunteers can view pending summaries, start verification sessions,
approve or reject summaries, and track their hours.
"""

import asyncio
import logging
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from api.auth import get_current_volunteer
from models.schemas import Summary, Volunteer
from social.pipeline import run_social_pipeline
from storage import (
    complete_verification_session,
    create_verification_session,
    get_minutes,
    get_summary,
    get_volunteer_sessions,
    list_pending_summaries,
    update_summary_status,
    update_summary_social,
    update_volunteer_hours,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/verify", tags=["verify"])


# --- Request/Response Models ---


class StartSessionResponse(BaseModel):
    session_id: str


class ApproveRequest(BaseModel):
    session_id: str
    edited_summary: Optional[str] = None
    notes: Optional[str] = None


class RejectRequest(BaseModel):
    session_id: str
    reason: str


class SuccessResponse(BaseModel):
    success: bool
    summary_id: str


class HoursResponse(BaseModel):
    total_hours: float
    sessions: list


# --- Endpoints ---


@router.get("/pending")
async def get_pending_summaries(volunteer: Volunteer = Depends(get_current_volunteer)):
    """List all summaries with status='pending'.
    
    Includes the related minute's title, meeting_date, and raw OCR text.
    Requires a valid Bearer token.
    """
    try:
        pending = list_pending_summaries()
        return {"summaries": pending, "count": len(pending)}
    except Exception as e:
        logger.error(f"Failed to list pending summaries: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to list pending summaries: {str(e)}",
        )


@router.get("/{summary_id}")
async def get_summary_detail(
    summary_id: str,
    volunteer: Volunteer = Depends(get_current_volunteer),
):
    """Get full detail of a single summary, including raw OCR text.
    
    Requires a valid Bearer token.
    Returns 404 if the summary is not found.
    """
    summary = get_summary(summary_id)
    if not summary:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Summary {summary_id} not found",
        )

    return {
        "id": summary.id,
        "minutes_id": summary.minutes_id,
        "summary": summary.summary,
        "key_decisions": summary.key_decisions,
        "budget_items": summary.budget_items,
        "public_comment_opportunities": summary.public_comment_opportunities,
        "items": summary.items,
        "big_picture": summary.big_picture,
        "what_you_can_do": summary.what_you_can_do,
        "category": summary.category,
        "neighborhood_impact": summary.neighborhood_impact,
        "status": summary.status,
        "created_at": summary.created_at.isoformat() if summary.created_at else None,
    }


@router.post("/{summary_id}/start", response_model=StartSessionResponse)
async def start_verification_session(
    summary_id: str,
    volunteer: Volunteer = Depends(get_current_volunteer),
):
    """Start a new verification session for a summary.
    
    Creates a new verification_sessions row with started_at = NOW().
    Requires a valid Bearer token.
    Returns 404 if the summary is not found.
    Returns 409 if the summary is not in 'pending' status.
    """
    summary = get_summary(summary_id)
    if not summary:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Summary {summary_id} not found",
        )

    if summary.status != "pending":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Summary is already {summary.status}. Only pending summaries can be verified.",
        )

    try:
        session_id = create_verification_session(
            volunteer_id=volunteer.user_id,
            summary_id=summary_id,
        )
        logger.info(
            f"Verification session started: volunteer={volunteer.user_id}, "
            f"summary={summary_id}, session={session_id}"
        )
        return StartSessionResponse(session_id=str(session_id))
    except Exception as e:
        logger.error(f"Failed to create verification session: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to start verification session: {str(e)}",
        )


@router.post("/{summary_id}/approve", response_model=SuccessResponse)
async def approve_summary(
    summary_id: str,
    request: ApproveRequest,
    volunteer: Volunteer = Depends(get_current_volunteer),
):
    """Approve a summary after verification.
    
    Updates the verification session with ended_at, duration_seconds,
    and action='approved'. Updates the summary with status='verified',
    verified_by, and verified_at. If edited_summary is provided, updates
    the summary text. Triggers the social media pipeline as a background
    task (card generation, storage upload, Facebook/Instagram posting).
    
    Requires a valid Bearer token.
    Returns 404 if the summary or session is not found.
    """
    summary = get_summary(summary_id)
    if not summary:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Summary {summary_id} not found",
        )

    if summary.status != "pending":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Summary is already {summary.status}. Only pending summaries can be approved.",
        )

    try:
        # Complete the verification session
        complete_verification_session(
            session_id=request.session_id,
            action="approved",
            notes=request.notes,
        )

        # Update the summary status
        now = datetime.now(timezone.utc)
        update_summary_status(
            summary_id=summary_id,
            status="verified",
            verified_by=volunteer.user_id,
            verified_at=now,
            edited_summary=request.edited_summary,
        )

        # Add volunteer hours (e.g., 0.5 hours per verification)
        update_volunteer_hours(volunteer.user_id, 0.5)

        # Fire social pipeline as a background task (non-blocking)
        async def _post_to_social():
            try:
                # Fetch minutes to get city and meeting_date
                minutes = get_minutes(summary.minutes_id)
                city = f"{minutes.city}, {minutes.state}" if minutes else "Paris, Texas"
                meeting_date = minutes.meeting_date.isoformat() if minutes and minutes.meeting_date else ""

                result = await run_social_pipeline(
                    summary_id=str(summary_id),
                    headline=summary.neighborhood_impact or "",
                    theme=summary.category or "City Council",
                    summary_text=(summary.summary or "")[:200],
                    city=city,
                    meeting_date=meeting_date,
                )
                if result["success"]:
                    update_summary_social(summary_id, result["image_url"])
                    logger.info(
                        f"Social pipeline completed for summary {summary_id}: "
                        f"fb={result['facebook_post_id']}, ig={result['instagram_media_id']}"
                    )
                else:
                    logger.warning(f"Social pipeline completed with partial/failure for summary {summary_id}")
            except Exception as e:
                logger.error(f"Social pipeline failed for summary {summary_id}: {e}")

        asyncio.create_task(_post_to_social())

        logger.info(
            f"Summary approved: summary={summary_id}, "
            f"volunteer={volunteer.user_id}, session={request.session_id}"
        )

        return SuccessResponse(success=True, summary_id=summary_id)

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to approve summary: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to approve summary: {str(e)}",
        )


@router.post("/{summary_id}/reject", response_model=SuccessResponse)
async def reject_summary(
    summary_id: str,
    request: RejectRequest,
    volunteer: Volunteer = Depends(get_current_volunteer),
):
    """Reject a summary after verification.
    
    Updates the verification session with ended_at, duration_seconds,
    and action='rejected'. Updates the summary with status='rejected'
    and rejection_reason.
    
    Requires a valid Bearer token.
    Returns 404 if the summary or session is not found.
    """
    summary = get_summary(summary_id)
    if not summary:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Summary {summary_id} not found",
        )

    if summary.status != "pending":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Summary is already {summary.status}. Only pending summaries can be rejected.",
        )

    try:
        # Complete the verification session
        complete_verification_session(
            session_id=request.session_id,
            action="rejected",
            notes=request.reason,
        )

        # Update the summary status
        update_summary_status(
            summary_id=summary_id,
            status="rejected",
            verified_by=volunteer.user_id,
            rejection_reason=request.reason,
        )

        logger.info(
            f"Summary rejected: summary={summary_id}, "
            f"volunteer={volunteer.user_id}, session={request.session_id}, "
            f"reason={request.reason}"
        )

        return SuccessResponse(success=True, summary_id=summary_id)

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to reject summary: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to reject summary: {str(e)}",
        )


@router.get("/hours", response_model=HoursResponse)
async def get_volunteer_hours(volunteer: Volunteer = Depends(get_current_volunteer)):
    """Get the current volunteer's total hours and session history.
    
    Requires a valid Bearer token.
    Returns total_hours and a list of past verification sessions.
    """
    try:
        sessions = get_volunteer_sessions(volunteer.user_id)
        return HoursResponse(
            total_hours=volunteer.hours_earned,
            sessions=sessions,
        )
    except Exception as e:
        logger.error(f"Failed to get volunteer hours: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get volunteer hours: {str(e)}",
        )
