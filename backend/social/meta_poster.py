"""
Meta Graph API poster for OpenCouncil.

Posts to Facebook Page and Instagram Business via Meta Graph API v22.0.
"""

import os
from typing import Optional

import httpx

META_GRAPH_URL = "https://graph.facebook.com/v22.0"
PAGE_ID = os.getenv("META_PAGE_ID", "")
PAGE_ACCESS_TOKEN = os.getenv("META_PAGE_ACCESS_TOKEN", "")
INSTAGRAM_ACCOUNT_ID = os.getenv("META_INSTAGRAM_ACCOUNT_ID", "")


async def upload_photo_to_facebook(image_url: str, caption: str) -> Optional[str]:
    """
    Post a photo to the Facebook Page.

    POST /{page-id}/photos?url={image_url}&caption={caption}&access_token={token}

    Returns the post ID or None on failure.
    """
    if not PAGE_ID or not PAGE_ACCESS_TOKEN:
        raise ValueError("META_PAGE_ID and META_PAGE_ACCESS_TOKEN must be set")

    url = f"{META_GRAPH_URL}/{PAGE_ID}/photos"
    params = {
        "url": image_url,
        "caption": caption,
        "access_token": PAGE_ACCESS_TOKEN,
    }

    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.post(url, params=params)
        if resp.status_code == 200:
            data = resp.json()
            return data.get("id")
        else:
            print(f"Facebook post failed: {resp.status_code} {resp.text}")
            return None


async def upload_photo_to_instagram(image_url: str, caption: str) -> Optional[str]:
    """
    Post a photo to Instagram Business account (two-step process).

    1. POST /{instagram-account-id}/media?image_url={url}&caption={caption}
    2. POST /{instagram-account-id}/media_publish?creation_id={media_id}

    Returns the media ID or None on failure.
    """
    if not INSTAGRAM_ACCOUNT_ID or not PAGE_ACCESS_TOKEN:
        raise ValueError(
            "META_INSTAGRAM_ACCOUNT_ID and META_PAGE_ACCESS_TOKEN must be set"
        )

    async with httpx.AsyncClient(timeout=30.0) as client:
        # Step 1: Create media container
        create_url = f"{META_GRAPH_URL}/{INSTAGRAM_ACCOUNT_ID}/media"
        create_params = {
            "image_url": image_url,
            "caption": caption,
            "access_token": PAGE_ACCESS_TOKEN,
        }
        create_resp = await client.post(create_url, params=create_params)

        if create_resp.status_code != 200:
            print(
                f"Instagram media creation failed: "
                f"{create_resp.status_code} {create_resp.text}"
            )
            return None

        creation_id = create_resp.json().get("id")
        if not creation_id:
            return None

        # Step 2: Publish the media container
        publish_url = f"{META_GRAPH_URL}/{INSTAGRAM_ACCOUNT_ID}/media_publish"
        publish_params = {
            "creation_id": creation_id,
            "access_token": PAGE_ACCESS_TOKEN,
        }
        publish_resp = await client.post(publish_url, params=publish_params)

        if publish_resp.status_code == 200:
            data = publish_resp.json()
            return data.get("id")
        else:
            print(
                f"Instagram publish failed: "
                f"{publish_resp.status_code} {publish_resp.text}"
            )
            return None


async def post_to_social(image_url: str, caption: str) -> dict:
    """
    Post to both Facebook and Instagram.

    Returns a dict with ``facebook_post_id`` and ``instagram_media_id`` keys.
    """
    results: dict = {"facebook_post_id": None, "instagram_media_id": None}

    fb_id = await upload_photo_to_facebook(image_url, caption)
    if fb_id:
        results["facebook_post_id"] = fb_id

    ig_id = await upload_photo_to_instagram(image_url, caption)
    if ig_id:
        results["instagram_media_id"] = ig_id

    return results
