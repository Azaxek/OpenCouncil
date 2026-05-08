"""
FastAPI server for Civic City Hub.

Provides REST endpoints for:
- Fetching agendas from connected cities
- Auto-summarizing agendas via DeepSeek LLM (saved persistently for everyone to see)
- Listing connected cities
- IP-based city detection for the frontend
- Health check

Summaries are stored in SQLite (local dev) or PostgreSQL (HF Spaces via Supabase).
API keys support encrypted storage for safe GitHub commits.
"""

import json
import os
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware

from connectors.laserfiche import LaserficheConnector
from crypto_utils import get_api_key_from_env
from models.schemas import Agenda, CityConfig, SummaryRequest, SummaryResponse
from parsers.llm_summarizer import LLMSummarizer
from storage import (
    init_db,
    save_agenda,
    get_agenda,
    list_agendas as db_list_agendas,
    save_summary,
    get_summary,
    list_summaries as db_list_summaries,
    summary_exists,
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


async def _auto_summarize(agenda: Agenda) -> Optional[SummaryResponse]:
    """Auto-summarize an agenda and save persistently."""
    global summarizer
    if not summarizer or not agenda:
        return None

    # Check if already summarized
    if summary_exists(agenda.id):
        print(f"[AUTO] Summary already exists for agenda {agenda.id}, skipping.")
        return get_summary(agenda.id)

    try:
        print(f"[AUTO] Summarizing agenda {agenda.id}...")
        summary = await summarizer.summarize_agenda(agenda)
        save_summary(summary)
        # Also attach summary text to the agenda itself
        agenda.summary = summary.summary
        save_agenda(agenda)
        print(f"[AUTO] Summary saved persistently for agenda {agenda.id}")
        return summary
    except Exception as e:
        print(f"[WARN] Auto-summarization failed for {agenda.id}: {e}")
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

    # Initialize LLM summarizer with DeepSeek API key
    # Supports both plaintext (DEEPSEEK_API_KEY) and encrypted (ENCRYPTED_DEEPSEEK_KEY + ENCRYPTION_KEY)
    api_key = get_api_key_from_env()
    if api_key:
        summarizer = LLMSummarizer(api_key=api_key)
        print("[OK] DeepSeek summarizer initialized")
    else:
        print("[WARN] No DEEPSEEK_API_KEY set. Summarization will be unavailable.")
        print("       Set DEEPSEEK_API_KEY in your environment or .env file.")
        print("       For GitHub-safe deployment, set ENCRYPTED_DEEPSEEK_KEY + ENCRYPTION_KEY.")

    print(f"[OK] Civic City Hub API ready - serving {PARIS_TX_CONFIG.name}, {PARIS_TX_CONFIG.state}")
    yield

    # Cleanup
    if connector:
        await connector.close()


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
    return {
        "status": "ok",
        "city": f"{PARIS_TX_CONFIG.name}, {PARIS_TX_CONFIG.state}",
        "llm_available": summarizer is not None,
        "llm_provider": "deepseek",
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


# --- Agendas ---

@app.get("/api/agendas")
async def list_agendas(limit: int = Query(10, ge=1, le=50)):
    """List recent agendas from the connected city."""
    if not connector:
        raise HTTPException(status_code=503, detail="Connector not initialized")

    try:
        # Try DB first
        agendas = db_list_agendas(limit=limit)
        if agendas:
            return {"agendas": agendas, "city": PARIS_TX_CONFIG.name}

        # Fall back to connector
        agendas = await connector.list_agendas(limit=limit)
        enriched = []
        for a in agendas:
            a["has_summary"] = summary_exists(a["id"])
            enriched.append(a)
        return {"agendas": enriched, "city": PARIS_TX_CONFIG.name}
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Failed to fetch agendas: {str(e)}")


@app.get("/api/agendas/{agenda_id}")
async def get_agenda(agenda_id: str):
    """Get a specific agenda with full details and its summary if available."""
    # Check persistent storage first
    agenda = get_agenda(agenda_id)
    if agenda:
        summary = get_summary(agenda_id)
        return {"agenda": agenda, "summary": summary}

    # Otherwise fetch fresh
    if not connector:
        raise HTTPException(status_code=503, detail="Connector not initialized")

    try:
        latest = await connector.get_latest_agenda()
        if latest and latest.id == agenda_id:
            save_agenda(latest)
            # Auto-summarize if not already done
            if summarizer and not summary_exists(agenda_id):
                await _auto_summarize(latest)
            return {
                "agenda": latest,
                "summary": get_summary(agenda_id),
            }
        else:
            # Try to find it in the list
            agendas = await connector.fetch_agenda_list()
            for a in agendas:
                if a["id"] == agenda_id:
                    if a.get("document_url"):
                        raw_text = await connector.fetch_agenda_document_text(a["document_url"])
                        items = connector._parse_agenda_items_from_text(raw_text) if raw_text else []
                        agenda = Agenda(
                            id=a["id"],
                            city=PARIS_TX_CONFIG.name,
                            state=PARIS_TX_CONFIG.state,
                            meeting_date=a["meeting_date"] or __import__("datetime").datetime.utcnow(),
                            title=a["title"],
                            url=a["url"] or "",
                            pdf_url=a.get("document_url"),
                            document_url=a.get("document_url"),
                            items=items,
                            raw_text=raw_text,
                        )
                        save_agenda(agenda)
                        # Auto-summarize if not already done
                        if summarizer and not summary_exists(agenda_id):
                            await _auto_summarize(agenda)
                        return {
                            "agenda": agenda,
                            "summary": get_summary(agenda_id),
                        }
            raise HTTPException(status_code=404, detail=f"Agenda {agenda_id} not found")
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Failed to fetch agenda: {str(e)}")


@app.post("/api/agendas/fetch-latest")
async def fetch_latest_agenda():
    """Fetch and store the latest agenda from the connected city.
    Auto-summarizes and saves the summary persistently so everyone can see it."""
    if not connector:
        raise HTTPException(status_code=503, detail="Connector not initialized")

    try:
        agenda = await connector.get_latest_agenda()
        if not agenda:
            raise HTTPException(status_code=404, detail="No agendas found")

        save_agenda(agenda)

        # Auto-summarize and save persistently
        if summarizer:
            await _auto_summarize(agenda)

        return {
            "agenda": agenda,
            "summary": get_summary(agenda.id),
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Failed to fetch latest agenda: {str(e)}")


# --- Summarization ---

@app.post("/api/summarize", response_model=SummaryResponse)
async def summarize_agenda(request: SummaryRequest):
    """Summarize an agenda using LLM. Results are saved persistently."""
    if not summarizer:
        raise HTTPException(
            status_code=503,
            detail="LLM summarizer not available. Set DEEPSEEK_API_KEY environment variable.",
        )

    # Check persistent store first (so everyone sees the same summary)
    existing = get_summary(request.agenda_id)
    if existing:
        return existing

    # Get the agenda
    agenda = get_agenda(request.agenda_id)
    if not agenda:
        # Try to fetch it
        if not connector:
            raise HTTPException(status_code=503, detail="Connector not initialized")
        try:
            latest = await connector.get_latest_agenda()
            if latest and latest.id == request.agenda_id:
                agenda = latest
                save_agenda(agenda)
            else:
                raise HTTPException(status_code=404, detail=f"Agenda {request.agenda_id} not found")
        except HTTPException:
            raise
        except Exception as e:
            raise HTTPException(status_code=502, detail=f"Failed to fetch agenda: {str(e)}")

    try:
        summary = await summarizer.summarize_agenda(agenda)
        save_summary(summary)
        return summary
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Summarization failed: {str(e)}")


@app.post("/api/summarize/text")
async def summarize_text(text: str, city: str = "Paris", state: str = "TX"):
    """Summarize raw agenda text directly."""
    if not summarizer:
        raise HTTPException(
            status_code=503,
            detail="LLM summarizer not available. Set DEEPSEEK_API_KEY environment variable.",
        )

    try:
        result = await summarizer.summarize_text(text, city=city, state=state)
        return result
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Summarization failed: {str(e)}")


# --- Summaries (shared, persistent) ---

@app.get("/api/summaries")
async def list_summaries():
    """List all saved summaries (persistent, shared for everyone to see)."""
    return {"summaries": db_list_summaries()}


@app.get("/api/summaries/{agenda_id}")
async def get_summary(agenda_id: str):
    """Get a specific saved summary."""
    summary = get_summary(agenda_id)
    if not summary:
        raise HTTPException(status_code=404, detail="Summary not found")
    return summary


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
