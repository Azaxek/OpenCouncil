"""
FastAPI server for Civic City Hub.

Provides REST endpoints for:
- Fetching minutes from connected cities
- Auto-summarizing minutes via DeepSeek LLM (saved persistently for everyone to see)
- Listing connected cities
- IP-based city detection for the frontend
- Health check

Summaries are stored in SQLite (local dev) or PostgreSQL (HF Spaces via Supabase).
API keys support encrypted storage for safe GitHub commits.
"""

import json
import os
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware

from connectors.laserfiche import LaserficheConnector
from crypto_utils import get_api_key_from_env
from models.schemas import CityConfig, Minutes, SummaryRequest, SummaryResponse
from parsers.llm_summarizer import LLMSummarizer
from storage import (
    init_db,
    save_minutes,
    get_minutes,
    list_minutes as db_list_minutes,
    save_minutes_summary,
    get_minutes_summary,
    minutes_summary_exists,
    reset_database,
    USE_POSTGRES,
)


# --- Configuration ---
CITIES_DB_PATH = Path(__file__).parent.parent / "data" / "cities.json"

PARIS_TX_CONFIG = CityConfig(
    name="Paris",
    state="TX",
    website_url="https://www.paristexas.gov",
    agenda_center_url="https://www.paristexas.gov/AgendaCenter",
    connector_type="laserfiche",
    laserfiche_url="https://documents.paristexas.gov/weblink",
)

# Global connector instance
connector: Optional[LaserficheConnector] = None
summarizer: Optional[LLMSummarizer] = None


def _load_cities_db() -> dict:
    """Load the cities database from JSON."""
    try:
        with open(CITIES_DB_PATH) as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {"cities": [], "default_city": "paris-tx"}


def _detect_city_from_ip(request: Request) -> dict:
    """Detect the user's city based on IP address.
    
    Uses x-forwarded-for header (set by reverse proxies like Vercel/Railway)
    or the direct remote address.
    
    For now, returns the default city since we only have Paris, TX.
    When more cities are added, this will use a geolocation service.
    """
    # Get client IP
    forwarded = request.headers.get("x-forwarded-for")
    client_ip = forwarded.split(",")[0].strip() if forwarded else request.client.host if request.client else "127.0.0.1"
    
    cities_db = _load_cities_db()
    default_id = cities_db.get("default_city", "paris-tx")
    
    # Find the default city
    default_city = None
    for c in cities_db.get("cities", []):
        if c["id"] == default_id:
            default_city = c
            break
    
    if not default_city and cities_db.get("cities"):
        default_city = cities_db["cities"][0]
    
    return {
        "client_ip": client_ip,
        "city": default_city or {"id": "paris-tx", "name": "Paris", "state": "TX"},
        "all_cities": [
            {"id": c["id"], "name": c["name"], "state": c["state"], "full_name": c.get("full_name"), "active": c.get("active", False)}
            for c in cities_db.get("cities", [])
        ],
    }


async def _auto_summarize_minutes(minutes: Minutes) -> Optional[SummaryResponse]:
    """Auto-summarize minutes and save persistently."""
    global summarizer, connector
    if not summarizer or not minutes:
        return None

    # Check if already summarized
    if minutes_summary_exists(minutes.id):
        print(f"[AUTO] Summary already exists for minutes {minutes.id}, skipping.")
        return get_minutes_summary(minutes.id)

    try:
        print(f"[AUTO] Summarizing minutes {minutes.id}...")

        # If the document has page image URLs, provide an image fetcher
        # for OCR-based summarization (even if raw_text is a stub like
        # "[This document is a scanned image...]")
        image_fetcher = None
        if (
            minutes.page_image_urls
            and connector
            and minutes.document_url
        ):
            image_fetcher = lambda: connector.fetch_page_images(
                minutes.document_url
            )

        summary = await summarizer.summarize_minutes(
            minutes,
            image_fetcher=image_fetcher,
        )
        save_minutes_summary(minutes.id, summary)
        # Also attach summary text to the minutes itself
        minutes.summary = summary.summary
        save_minutes(minutes)
        print(f"[AUTO] Minutes summary saved persistently for {minutes.id}")
        return summary
    except Exception as e:
        print(f"[WARN] Auto-summarization failed for minutes {minutes.id}: {e}")
        return None


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Manage application lifecycle."""
    global connector, summarizer

    # Initialize database (SQLite locally, PostgreSQL on HF Spaces)
    init_db()
    print(f"[OK] Database initialized ({'PostgreSQL' if os.getenv('DATABASE_URL') else 'SQLite'})")

    # Initialize Laserfiche connector for Paris, TX
    connector = LaserficheConnector(
        city=PARIS_TX_CONFIG.name,
        state=PARIS_TX_CONFIG.state,
    )

    # Initialize LLM summarizer with DeepSeek key
    # DeepSeek handles both text-based summarization and OCR-extracted text
    # Tesseract OCR (free, open-source) extracts text from scanned images,
    # then DeepSeek summarizes it — no paid API keys needed!
    #
    # DeepSeek key supports both plaintext (DEEPSEEK_API_KEY) and
    # encrypted (ENCRYPTED_DEEPSEEK_KEY + ENCRYPTION_KEY) modes.
    deepseek_key = get_api_key_from_env()

    if deepseek_key:
        summarizer = LLMSummarizer(
            deepseek_key=deepseek_key,
        )
        print(f"[OK] LLM summarizer initialized with DeepSeek (text + OCR)")
    else:
        print("[WARN] No DEEPSEEK_API_KEY set. Summarization will be unavailable.")
        print("       Set DEEPSEEK_API_KEY in your environment or .env file.")
        print("       For GitHub-safe deployment, set ENCRYPTED_DEEPSEEK_KEY + ENCRYPTION_KEY.")

    print(f"[OK] Civic City Hub API ready - serving {PARIS_TX_CONFIG.name}, {PARIS_TX_CONFIG.state}")
    yield

    # Cleanup
    if connector:
        await connector.close()
    if summarizer:
        await summarizer.close()


app = FastAPI(
    title="Civic City Hub API",
    description="Making local government understandable for everyone.",
    version="0.1.0",
    lifespan=lifespan,
)

# CORS — allow frontend dev server and Vercel deployments
_origins = [
    "http://localhost:3000",
    "http://127.0.0.1:3000",
]

# In production (Vercel), allow the Vercel deployment domain
_vercel_url = os.getenv("NEXT_PUBLIC_VERCEL_URL")
if _vercel_url:
    _origins.append(f"https://{_vercel_url}")

app.add_middleware(
    CORSMiddleware,
    allow_origins=_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# --- Health ---

@app.get("/health")
async def health():
    """Health check endpoint."""
    ocr_available = False
    if summarizer:
        ocr_available = (
            summarizer._pytesseract_available
            and summarizer._pillow_available
        )
    return {
        "status": "ok",
        "city": f"{PARIS_TX_CONFIG.name}, {PARIS_TX_CONFIG.state}",
        "llm_available": summarizer is not None,
        "ocr_available": ocr_available,
        "storage": "postgresql" if USE_POSTGRES else "sqlite",
    }


# --- Cities ---

@app.get("/api/cities")
async def list_cities():
    """List all connected cities."""
    return {
        "cities": [
            {
                "name": PARIS_TX_CONFIG.name,
                "state": PARIS_TX_CONFIG.state,
                "website": PARIS_TX_CONFIG.website_url,
                "agenda_center": PARIS_TX_CONFIG.agenda_center_url,
                "connector": PARIS_TX_CONFIG.connector_type,
                "active": PARIS_TX_CONFIG.active,
            }
        ]
    }


# --- Minutes (official records of what happened) ---

@app.get("/api/minutes")
async def list_minutes(limit: int = Query(10, ge=1, le=50)):
    """List recent minutes from the connected city."""
    if not connector:
        raise HTTPException(status_code=503, detail="Connector not initialized")

    try:
        # Try DB first
        minutes_list = db_list_minutes(limit=limit)
        if minutes_list:
            return {"minutes": minutes_list, "city": PARIS_TX_CONFIG.name}

        # Fall back to connector
        minutes_list = await connector.list_minutes(limit=limit)
        enriched = []
        for m in minutes_list:
            m["has_summary"] = minutes_summary_exists(m["id"])
            enriched.append(m)
        return {"minutes": enriched, "city": PARIS_TX_CONFIG.name}
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Failed to fetch minutes: {str(e)}")


@app.get("/api/minutes/{minutes_id}")
async def get_minutes_endpoint(minutes_id: str):
    """Get a specific minutes document with full details and its summary if available."""
    # Check persistent storage first
    minutes = get_minutes(minutes_id)
    if minutes:
        summary = get_minutes_summary(minutes_id)
        return {"minutes": minutes, "summary": summary}

    # Otherwise fetch fresh
    if not connector:
        raise HTTPException(status_code=503, detail="Connector not initialized")

    try:
        latest = await connector.get_latest_minutes()
        if latest and latest.id == minutes_id:
            save_minutes(latest)
            # Auto-summarize if not already done
            if summarizer and not minutes_summary_exists(minutes_id):
                await _auto_summarize_minutes(latest)
            return {
                "minutes": latest,
                "summary": get_minutes_summary(minutes_id),
            }
        else:
            # Try to find it in the list
            minutes_list = await connector.fetch_minutes_list()
            for m in minutes_list:
                if m["id"] == minutes_id:
                    if m.get("document_url"):
                        raw_text = await connector.fetch_document_text(m["document_url"])
                        page_image_urls = await connector.fetch_page_image_urls(
                            m["document_url"]
                        )
                        minutes = Minutes(
                            id=m["id"],
                            city=PARIS_TX_CONFIG.name,
                            state=PARIS_TX_CONFIG.state,
                            meeting_date=m["meeting_date"] or datetime.now(timezone.utc),
                            title=m["title"],
                            url=m["url"] or "",
                            document_url=m.get("document_url"),
                            raw_text=raw_text,
                            page_image_urls=page_image_urls,
                        )
                        save_minutes(minutes)
                        # Auto-summarize if not already done
                        if summarizer and not minutes_summary_exists(minutes_id):
                            await _auto_summarize_minutes(minutes)
                        return {
                            "minutes": minutes,
                            "summary": get_minutes_summary(minutes_id),
                        }
            raise HTTPException(status_code=404, detail=f"Minutes {minutes_id} not found")
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Failed to fetch minutes: {str(e)}")


@app.post("/api/minutes/reset")
async def reset_minutes():
    """Delete ALL stored minutes and summaries from the database.
    This forces a fresh fetch of the latest minutes on next request."""
    try:
        reset_database()
        return {"status": "ok", "message": "Database reset. All minutes and summaries deleted."}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to reset database: {str(e)}")


@app.post("/api/minutes/fetch-latest")
async def fetch_latest_minutes():
    """Fetch and store the latest minutes from the connected city.
    Auto-summarizes and saves the summary persistently so everyone can see it."""
    if not connector:
        raise HTTPException(status_code=503, detail="Connector not initialized")

    try:
        minutes = await connector.get_latest_minutes()
        if not minutes:
            raise HTTPException(status_code=404, detail="No minutes found")

        save_minutes(minutes)

        # Auto-summarize and save persistently
        if summarizer:
            await _auto_summarize_minutes(minutes)

        return {
            "minutes": minutes,
            "summary": get_minutes_summary(minutes.id),
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Failed to fetch latest minutes: {str(e)}")


@app.post("/api/minutes/summarize")
async def summarize_minutes_endpoint(request: SummaryRequest):
    """Summarize minutes using LLM. Results are saved persistently."""
    if not summarizer:
        raise HTTPException(
            status_code=503,
            detail="LLM summarizer not available. Set DEEPSEEK_API_KEY environment variable.",
        )

    # Check persistent store first (so everyone sees the same summary)
    existing = get_minutes_summary(request.minutes_id)
    if existing:
        return existing

    # Get the minutes
    minutes = get_minutes(request.minutes_id)
    if not minutes:
        # Try to fetch it
        if not connector:
            raise HTTPException(status_code=503, detail="Connector not initialized")
        try:
            latest = await connector.get_latest_minutes()
            if latest and latest.id == request.minutes_id:
                minutes = latest
                save_minutes(minutes)
            else:
                raise HTTPException(status_code=404, detail=f"Minutes {request.minutes_id} not found")
        except HTTPException:
            raise
        except Exception as e:
            raise HTTPException(status_code=502, detail=f"Failed to fetch minutes: {str(e)}")

    try:
        # Provide image fetcher for OCR-based summarization
        # (even if raw_text is a stub like "[This document is a scanned image...]")
        image_fetcher = None
        if (
            minutes.page_image_urls
            and connector
            and minutes.document_url
        ):
            image_fetcher = lambda: connector.fetch_page_images(
                minutes.document_url
            )

        summary = await summarizer.summarize_minutes(
            minutes,
            image_fetcher=image_fetcher,
        )
        save_minutes_summary(minutes.id, summary)
        # Save minutes too — OCR may have populated raw_text
        save_minutes(minutes)
        return summary
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Summarization failed: {str(e)}")


# --- City Configuration ---

@app.get("/api/config")
async def get_config():
    """Get the current city configuration."""
    return {
        "city": PARIS_TX_CONFIG.name,
        "state": PARIS_TX_CONFIG.state,
        "website": PARIS_TX_CONFIG.website_url,
        "agenda_center": PARIS_TX_CONFIG.agenda_center_url,
        "laserfiche": PARIS_TX_CONFIG.laserfiche_url,
        "connector_type": PARIS_TX_CONFIG.connector_type,
    }


# --- IP-based City Detection ---

@app.get("/api/detect-city")
async def detect_city(request: Request):
    """Detect the user's city based on their IP address.
    
    Returns:
    - client_ip: The detected IP
    - city: The matched city object
    - all_cities: All available cities for the city selector
    """
    return _detect_city_from_ip(request)
