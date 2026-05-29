"""
Social media pipeline orchestrator for OpenCouncil.

Ties card generation, Supabase Storage upload, and social posting together.
"""

import os
from typing import Optional

import httpx

from .card_generator import generate_card
from .meta_poster import post_to_social

SUPABASE_URL = os.getenv("NEXT_PUBLIC_SUPABASE_URL", "")
SUPABASE_SERVICE_ROLE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY", "")
STORAGE_BUCKET = os.getenv("SUPABASE_STORAGE_BUCKET", "opencouncil-cards")


async def upload_to_supabase_storage(
    image_bytes: bytes, filename: str
) -> Optional[str]:
    """
    Upload image bytes to Supabase Storage.

    PUT /storage/v1/object/{bucket}/{filename}

    Returns the public URL or None on failure.
    """
    if not SUPABASE_URL or not SUPABASE_SERVICE_ROLE_KEY:
        raise ValueError(
            "NEXT_PUBLIC_SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY must be set"
        )

    upload_url = f"{SUPABASE_URL}/storage/v1/object/{STORAGE_BUCKET}/{filename}"
    headers = {
        "Authorization": f"Bearer {SUPABASE_SERVICE_ROLE_KEY}",
        "Content-Type": "image/png",
    }

    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.put(upload_url, content=image_bytes, headers=headers)
        if resp.status_code in (200, 201):
            public_url = (
                f"{SUPABASE_URL}/storage/v1/object/public/"
                f"{STORAGE_BUCKET}/{filename}"
            )
            return public_url
        else:
            print(
                f"Supabase storage upload failed: "
                f"{resp.status_code} {resp.text}"
            )
            return None


async def run_social_pipeline(
    summary_id: str,
    headline: str,
    theme: str,
    summary_text: str,
    city: str,
    meeting_date: str,
    logo_path: Optional[str] = None,
) -> dict:
    """
    Run the full social media pipeline:

    1. Generate a 1080x1080 news card image.
    2. Upload the image to Supabase Storage.
    3. Post the image + caption to Facebook and Instagram.

    Returns a dict with ``image_url``, ``facebook_post_id``,
    ``instagram_media_id``, and ``success``.
    """
    result: dict = {
        "image_url": None,
        "facebook_post_id": None,
        "instagram_media_id": None,
        "success": False,
    }

    # 1. Generate card image
    filename = f"summary_{summary_id}.png"
    card_bytes = await generate_card(
        headline=headline,
        theme=theme,
        summary_text=summary_text,
        city=city,
        meeting_date=meeting_date,
        logo_path=logo_path,
    )

    # 2. Upload to Supabase Storage
    image_url = await upload_to_supabase_storage(card_bytes, filename)
    if not image_url:
        print("Failed to upload image to Supabase Storage")
        return result

    result["image_url"] = image_url

    # 3. Build caption
    caption = (
        f"\U0001f4cb {headline}\n\n"
        f"{summary_text}\n\n"
        f"\U0001f4cd {city}\n"
        f"\U0001f4c5 {meeting_date}\n\n"
        f"Read the full meeting summary at OpenCouncil.\n"
        f"#CivicEngagement #LocalGovernment #CityCouncil #Transparency"
    )

    # 4. Post to social media
    social_results = await post_to_social(image_url, caption)
    result["facebook_post_id"] = social_results.get("facebook_post_id")
    result["instagram_media_id"] = social_results.get("instagram_media_id")

    result["success"] = bool(
        result["facebook_post_id"] or result["instagram_media_id"]
    )

    return result
