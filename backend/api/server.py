"""
FastAPI server for OpenCouncil.

Provides REST endpoints for:
- Fetching minutes from connected cities
- Auto-summarizing minutes via Groq LLM / Llama 8B (saved persistently for everyone to see)
- Listing connected cities
- IP-based city detection for the frontend
- Health check

Summaries are stored in SQLite (local dev) or PostgreSQL (HF Spaces via Supabase).
API keys support encrypted storage for safe GitHub commits.

Scheduled scraping: APScheduler runs a background job every 6 hours to fetch
and summarize new meeting minutes automatically.
"""

import json
import os
import re
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

try:
    from apscheduler.schedulers.asyncio import AsyncIOScheduler
    _has_scheduler = True
except ImportError:
    AsyncIOScheduler = None
    _has_scheduler = False
from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from api.auth import router as auth_router
from api.verify import router as verify_router
from connectors.civicplus import CivicPlusConnector
from connectors.generic_pdf import GenericPDFConnector
from connectors.laserfiche import LaserficheConnector
from connectors.onbase import OnBaseConnector
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

# Default city for backward compatibility
PARIS_TX_CONFIG = CityConfig(
    name="Paris",
    state="TX",
    website_url="https://www.paristexas.gov",
    agenda_center_url="https://www.paristexas.gov/AgendaCenter",
    connector_type="laserfiche",
    laserfiche_url="https://documents.paristexas.gov/weblink",
)

# Global state
connector: object = None  # Backward compatibility
connectors: dict[str, object] = {}
city_configs: dict[str, CityConfig] = {}
summarizer: Optional[LLMSummarizer] = None
scheduler: Optional[AsyncIOScheduler] = None
_last_scraped_at: Optional[datetime] = None
_scrape_errors: int = 0
_default_city_id: str = "paris-tx"


def _load_cities_db() -> dict:
    """Load the cities database from JSON."""
    try:
        with open(CITIES_DB_PATH) as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {"cities": [], "default_city": "paris-tx"}


def _build_city_config(city_data: dict) -> CityConfig:
    """Build a CityConfig from JSON city data."""
    connector_type = city_data.get("connector_type", "laserfiche")
    config = CityConfig(
        name=city_data.get("name", "Unknown"),
        state=city_data.get("state", "TX"),
        website_url=city_data.get("website_url", ""),
        agenda_center_url=city_data.get("agenda_center_url", ""),
        connector_type=connector_type,
        laserfiche_url=city_data.get("laserfiche_url"),
        rss_feed_url=city_data.get("rss_feed_url"),
        active=city_data.get("active", False),
    )
    # Store extra config in a dict for connector init
    config._extra = city_data
    return config


def _create_connector(config: CityConfig):
    """Create the appropriate connector based on config."""
    city_data = getattr(config, "_extra", {})
    connector_type = config.connector_type

    if connector_type == "laserfiche":
        return LaserficheConnector(
            city=config.name,
            state=config.state,
        )
    elif connector_type == "civicplus":
        return CivicPlusConnector(
            base_url=config.website_url,
            city=config.name,
            state=config.state,
        )
    elif connector_type == "generic_pdf":
        council_url = city_data.get("council_page_url", f"{config.website_url}/city-council")
        return GenericPDFConnector(
            council_url=council_url,
            city=config.name,
            state=config.state,
        )
    elif connector_type == "onbase":
        onbase_url = city_data.get(
            "onbase_url",
            f"https://agenda.{config.name.lower().replace(' ', '')}texas.gov/OnBaseAgendaOnline",
        )
        category_id = city_data.get("onbase_category_id", "105")
        return OnBaseConnector(
            base_url=onbase_url,
            city=config.name,
            state=config.state,
            category_id=category_id,
        )
    else:
        raise ValueError(f"Unknown connector type: {connector_type}")


async def _geo_locate_city(client_ip: str) -> Optional[dict]:
    """Use free ipapi.co to geolocate an IP and match to a known city.

    ipapi.co is free for up to 1,000 requests/day with no API key needed.
    Falls back silently on failure.
    """
    try:
        import httpx
        async with httpx.AsyncClient(timeout=5.0) as client:
            r = await client.get(f"https://ipapi.co/{client_ip}/json/")
            if r.status_code != 200:
                return None
            data = r.json()
            city = data.get("city", "")
            state = data.get("region_code", "")
            zip_code = data.get("postal", "")

            if not city or not state:
                return None

            # Match against known cities
            cities_db = _load_cities_db()
            for c in cities_db.get("cities", []):
                c_name = c.get("name", "").lower()
                c_state = c.get("state", "").lower()
                # Fuzzy match: city name contains detected or vice versa
                if (city.lower() in c_name or c_name in city.lower()) and state.lower() == c_state:
                    return c
                # Also try zip code partial match if city names differ
                # (e.g., "Frisco" is unambiguous in TX)
                if state.lower() == c_state and city.lower() in c.get("full_name", "").lower():
                    return c

            return None
    except Exception:
        return None


async def _detect_city_from_ip(request: Request) -> dict:
    """Detect the user's city based on their IP address.

    Uses x-forwarded-for header (set by reverse proxies like Vercel/Railway)
    or the direct remote address.

    First tries ipapi.co for geolocation, then falls back to the default city.
    """
    forwarded = request.headers.get("x-forwarded-for")
    client_ip = forwarded.split(",")[0].strip() if forwarded else request.client.host if request.client else "127.0.0.1"

    # Try geolocation
    geo_city = None
    if client_ip and client_ip != "127.0.0.1":
        geo_city = await _geo_locate_city(client_ip)

    cities_db = _load_cities_db()
    default_id = cities_db.get("default_city", _default_city_id)

    # If geolocation matched a city, use that
    if geo_city:
        detected_city = geo_city
    else:
        # Fall back to default
        detected_city = None
        for c in cities_db.get("cities", []):
            if c["id"] == default_id:
                detected_city = c
                break
        if not detected_city and cities_db.get("cities"):
            detected_city = cities_db["cities"][0]

    return {
        "client_ip": client_ip,
        "city": detected_city or {"id": "paris-tx", "name": "Paris", "state": "TX"},
        "all_cities": [
            {"id": c["id"], "name": c["name"], "state": c["state"],
             "full_name": c.get("full_name"), "active": c.get("active", False),
             "population": c.get("population"), "county": c.get("county"),
             "description": c.get("description"), "website_url": c.get("website_url")}
            for c in cities_db.get("cities", [])
        ],
    }


async def _auto_summarize_minutes(minutes: Minutes) -> Optional[SummaryResponse]:
    """Auto-summarize minutes and save persistently."""
    global summarizer
    if not summarizer or not minutes:
        return None

    if minutes_summary_exists(minutes.id):
        print(f"[AUTO] Summary already exists for minutes {minutes.id}, skipping.")
        return get_minutes_summary(minutes.id)

    try:
        print(f"[AUTO] Summarizing minutes {minutes.id}...")

        # Get the connector for this city
        city_key = f"{minutes.city.lower()}-{minutes.state.lower()}"
        conn = connectors.get(city_key)

        image_fetcher = None
        has_urls = (
            minutes.page_image_urls
            and isinstance(minutes.page_image_urls[0], str)
            and conn
            and minutes.document_url
        )
        if has_urls and hasattr(conn, 'fetch_page_images'):
            _page_urls = list(minutes.page_image_urls)
            image_fetcher = lambda: conn.fetch_page_images(
                minutes.document_url, page_urls=_page_urls
            )

        summary = await summarizer.summarize_minutes(
            minutes,
            image_fetcher=image_fetcher,
        )
        save_minutes_summary(minutes.id, summary)
        minutes.summary = summary.summary
        save_minutes(minutes)
        print(f"[AUTO] Minutes summary saved persistently for {minutes.id}")
        return summary
    except Exception as e:
        print(f"[WARN] Auto-summarization failed for minutes {minutes.id}: {e}")
        return None


async def _scheduled_scrape():
    """Background job: fetch latest minutes from ALL cities and auto-summarize."""
    global _last_scraped_at, _scrape_errors
    print("[SCHEDULER] Starting scheduled scrape of latest minutes from all cities...")
    try:
        if not connectors:
            print("[SCHEDULER] No connectors available, skipping.")
            return

        total_new = 0
        for city_key, conn in connectors.items():
            if not hasattr(conn, 'fetch_minutes_list'):
                continue

            city_name = city_key.split("-")[0].title()
            print(f"[SCHEDULER] Scraping {city_name}...")

            try:
                minutes_list = await conn.fetch_minutes_list()
                new_count = 0
                for m in minutes_list:
                    mid = m.get("id")
                    if not mid:
                        continue

                    existing = get_minutes(mid)
                    if existing and minutes_summary_exists(mid):
                        continue

                    if not existing:
                        try:
                            doc_url = m.get("document_url")
                            raw_text = None
                            page_image_urls: list[str] = []
                            if doc_url and hasattr(conn, 'fetch_document_text'):
                                raw_text = await conn.fetch_document_text(doc_url)
                                if raw_text:
                                    for line in raw_text.split("\n"):
                                        match = re.search(r'\[Page \d+: (.+)\]', line)
                                        if match:
                                            page_image_urls.append(match.group(1))
                                if not page_image_urls and hasattr(conn, 'fetch_page_image_urls'):
                                    page_image_urls = await conn.fetch_page_image_urls(doc_url)

                            minutes_obj = Minutes(
                                id=mid,
                                city=m.get("city", city_name),
                                state=m.get("state", "TX"),
                                meeting_date=m.get("meeting_date") or datetime.now(timezone.utc),
                                meeting_type=m.get("meeting_type", "City Council Meeting"),
                                title=m.get("title", "Meeting Minutes"),
                                url=m.get("url") or "",
                                document_url=doc_url,
                                raw_text=raw_text,
                                page_image_urls=page_image_urls,
                            )
                            save_minutes(minutes_obj)
                            new_count += 1
                            print(f"[SCHEDULER] Saved new minutes: {mid} for {city_name}")
                        except Exception as e:
                            print(f"[SCHEDULER] Failed to fetch minutes {mid}: {e}")
                            continue
                    else:
                        minutes_obj = existing

                    if summarizer and not minutes_summary_exists(mid):
                        try:
                            await _auto_summarize_minutes(minutes_obj)
                        except Exception as e:
                            print(f"[SCHEDULER] Summarization failed for {mid}: {e}")

                total_new += new_count
                print(f"[SCHEDULER] {city_name}: {new_count} new minutes")
            except Exception as e:
                print(f"[SCHEDULER] Failed to scrape {city_name}: {e}")

        _last_scraped_at = datetime.now(timezone.utc)
        _scrape_errors = 0
        print(f"[SCHEDULER] Scrape complete. {total_new} new minutes total.")
    except Exception as e:
        _scrape_errors += 1
        print(f"[SCHEDULER] Scrape failed (error #{_scrape_errors}): {e}")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Manage application lifecycle."""
    global connector, summarizer, scheduler, connectors, city_configs, _default_city_id

    # Initialize database — wrap in try/except so the health endpoint works even if DB fails
    try:
        init_db()
        print(f"[OK] Database initialized ({'PostgreSQL' if os.getenv('DATABASE_URL') else 'SQLite'})")
    except Exception as e:
        print(f"[WARN] Database initialization failed: {e}")
        print("[WARN] Running with limited functionality (DB queries will fail)")

    # Load cities and initialize connectors
    try:
        cities_db = _load_cities_db()
        _default_city_id = cities_db.get("default_city", "paris-tx")
    except Exception as e:
        print(f"[WARN] Failed to load cities database: {e}")
        cities_db = {"cities": [], "default_city": "paris-tx"}

    # Keep the global 'connector' var for backwards compatibility
    connector = None

    for city_data in cities_db.get("cities", []):
        if not city_data.get("active", False):
            print(f"[SKIP] {city_data.get('name')}, {city_data.get('state')} is inactive")
            continue

        try:
            config = _build_city_config(city_data)
            conn = _create_connector(config)
            city_key = f"{config.name.lower()}-{config.state.lower()}"
            connectors[city_key] = conn
            city_configs[city_key] = config
            print(f"[OK] {config.name}, {config.state} connector initialized ({config.connector_type})")

            # Set as default connector for backward compatibility
            if city_data.get("id") == _default_city_id:
                connector = conn
        except Exception as e:
            print(f"[WARN] Failed to initialize {city_data.get('name')}: {e}")

    # Initialize LLM summarizer
    grok_key = get_api_key_from_env()
    if grok_key:
        summarizer = LLMSummarizer(grok_key=grok_key)
        print(f"[OK] LLM summarizer initialized with Groq / Llama 8B (text + OCR)")
    else:
        print("[WARN] No GROK_API_KEY set. Summarization will be unavailable.")

    # Start background scheduler (local only — Vercel uses cron jobs)
    import asyncio
    if _has_scheduler and not os.getenv("VERCEL"):
        scheduler = AsyncIOScheduler(timezone="UTC")
        scheduler.add_job(
            _scheduled_scrape,
            trigger="interval",
            hours=6,
            id="scrape_minutes",
            name="Fetch & summarize latest minutes",
            replace_existing=True,
            max_instances=1,
        )
        scheduler.start()
        print("[OK] Background scheduler started — will auto-scrape every 6 hours")
        asyncio.create_task(_scheduled_scrape())
        print("[OK] Initial scrape queued — minutes will appear shortly")
    else:
        print("[OK] Running in serverless mode (no scheduler)")

    print(f"[OK] OpenCouncil API ready - serving {len(connectors)} cities")
    yield

    # Cleanup
    if _has_scheduler and scheduler and scheduler.running:
        scheduler.shutdown(wait=False)
    for conn in connectors.values():
        if hasattr(conn, 'close'):
            await conn.close()
    if summarizer:
        await summarizer.close()


app = FastAPI(
    title="OpenCouncil API",
    description="Making local government understandable for everyone.",
    version="0.2.0",
    lifespan=lifespan,
)

# CORS — allow frontend dev server and Vercel deployments
_origins = [
    "http://localhost:3000",
    "http://127.0.0.1:3000",
]

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

# Register auth and verification routers
app.include_router(auth_router)
app.include_router(verify_router)


def _get_connector(city_id: str = None):
    """Get the appropriate connector for the given city or default."""
    if city_id:
        for key, conn in connectors.items():
            if key.startswith(city_id.lower().replace("-", "-")):
                return conn
    # Fall back to default
    for key, conn in connectors.items():
        if key.startswith(_default_city_id.replace("-", "-")):
            return conn
    return connector  # fallback to global


# --- Health ---

@app.get("/health")
async def health():
    """Health check endpoint."""
    ocr_available = False
    ocr_engines = []
    if summarizer:
        if summarizer._easyocr_available:
            ocr_engines.append("easyocr")
        if summarizer._pytesseract_available:
            ocr_engines.append("tesseract")
        if summarizer._pillow_available:
            ocr_engines.append("pillow")
        if summarizer._numpy_available:
            ocr_engines.append("numpy")
        ocr_available = bool(ocr_engines)

    next_scrape = None
    if scheduler and scheduler.running:
        job = scheduler.get_job("scrape_minutes")
        if job and job.next_run_time:
            next_scrape = job.next_run_time.isoformat()

    return {
        "status": "ok",
        "cities_connected": len(connectors),
        "cities": list(city_configs.keys()),
        "llm_available": summarizer is not None,
        "llm_provider": "Groq / llama-3.1-8b-instant" if summarizer else None,
        "ocr_available": ocr_available,
        "ocr_engines": ocr_engines,
        "storage": "postgresql" if USE_POSTGRES else "sqlite",
        "scheduler": {
            "running": scheduler.running if scheduler else False,
            "last_scraped_at": _last_scraped_at.isoformat() if _last_scraped_at else None,
            "next_scrape_at": next_scrape,
            "scrape_errors": _scrape_errors,
        },
    }


# --- Cities ---

@app.get("/api/cities")
async def list_cities():
    """List all connected cities."""
    cities_db = _load_cities_db()
    return {
        "cities": [
            {
                "id": c["id"],
                "name": c["name"],
                "state": c["state"],
                "full_name": c.get("full_name"),
                "website": c.get("website_url"),
                "agenda_center": c.get("agenda_center_url"),
                "connector": c.get("connector_type"),
                "population": c.get("population"),
                "county": c.get("county"),
                "description": c.get("description"),
                "tags": c.get("tags"),
                "active": c.get("active", False),
            }
            for c in cities_db.get("cities", [])
        ]
    }


# --- Minutes (official records of what happened) ---

def _get_minutes_for_city(minutes_list: list, city_name: str) -> list:
    """Filter or enrich minutes list with city info."""
    enriched = []
    for m in minutes_list:
        m["has_summary"] = minutes_summary_exists(m["id"])
        if "city" not in m:
            m["city"] = city_name
        enriched.append(m)
    return enriched


@app.get("/api/minutes")
async def list_minutes(
    limit: int = Query(10, ge=1, le=50),
    city: str = Query(None, description="City ID (e.g., 'paris-tx', 'sulphur-springs-tx')"),
):
    """List recent minutes from connected cities."""
    conn = _get_connector(city)
    if not conn:
        raise HTTPException(status_code=503, detail="No connector available")

    # Get city name for the response
    city_name = "Paris"
    for key, cfg in city_configs.items():
        if hasattr(conn, 'city') and conn.city == cfg.name:
            city_name = f"{cfg.name}, {cfg.state}"
            break

    try:
        minutes_list = db_list_minutes(limit=limit)
        if minutes_list:
            enriched = _get_minutes_for_city(minutes_list, city_name)
            return {"minutes": enriched, "city": city_name}

        if hasattr(conn, 'list_minutes'):
            minutes_list = await conn.list_minutes(limit=limit)
            enriched = _get_minutes_for_city(minutes_list, city_name)
            return {"minutes": enriched, "city": city_name}
        else:
            return {"minutes": [], "city": city_name}
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Failed to fetch minutes: {str(e)}")


@app.get("/api/minutes/{minutes_id}")
async def get_minutes_endpoint(minutes_id: str):
    """Get a specific minutes document with full details and its summary if available."""
    minutes = get_minutes(minutes_id)
    if minutes:
        summary = get_minutes_summary(minutes_id)
        return {"minutes": minutes, "summary": summary}

    # Try all connectors to find it
    for city_key, conn in connectors.items():
        if hasattr(conn, 'get_latest_minutes'):
            try:
                latest = await conn.get_latest_minutes()
                if latest and latest.id == minutes_id:
                    save_minutes(latest)
                    if summarizer and not minutes_summary_exists(minutes_id):
                        await _auto_summarize_minutes(latest)
                    return {
                        "minutes": latest,
                        "summary": get_minutes_summary(minutes_id),
                    }
            except Exception:
                continue

        # Try to search in the minutes list
        if hasattr(conn, 'fetch_minutes_list'):
            try:
                minutes_list = await conn.fetch_minutes_list(limit=50)
                for m in minutes_list:
                    if m["id"] == minutes_id:
                        doc_url = m.get("document_url")
                        raw_text = None
                        page_image_urls: list[str] = []
                        if doc_url and hasattr(conn, 'fetch_document_text'):
                            raw_text = await conn.fetch_document_text(doc_url)
                            if raw_text:
                                for line in raw_text.split("\n"):
                                    match = re.search(r'\[Page \d+: (.+)\]', line)
                                    if match:
                                        page_image_urls.append(match.group(1))
                            if not page_image_urls and hasattr(conn, 'fetch_page_image_urls'):
                                page_image_urls = await conn.fetch_page_image_urls(doc_url)

                        city_name = m.get("city", city_key.split("-")[0].title())
                        minutes = Minutes(
                            id=m["id"],
                            city=city_name,
                            state=m.get("state", "TX"),
                            meeting_date=m.get("meeting_date") or datetime.now(timezone.utc),
                            title=m["title"],
                            url=m.get("url") or "",
                            document_url=doc_url,
                            raw_text=raw_text,
                            page_image_urls=page_image_urls,
                        )
                        save_minutes(minutes)
                        if summarizer and not minutes_summary_exists(minutes_id):
                            await _auto_summarize_minutes(minutes)
                        return {
                            "minutes": minutes,
                            "summary": get_minutes_summary(minutes_id),
                        }
            except Exception:
                continue

    raise HTTPException(status_code=404, detail=f"Minutes {minutes_id} not found")


@app.post("/api/minutes/reset")
async def reset_minutes():
    """Delete ALL stored minutes and summaries from the database."""
    try:
        reset_database()
        return {"status": "ok", "message": "Database reset. All minutes and summaries deleted."}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to reset database: {str(e)}")


@app.post("/api/minutes/fetch-latest")
async def fetch_latest_minutes():
    """Fetch and store the latest minutes from all connected cities."""
    conn = _get_connector()
    if not conn:
        raise HTTPException(status_code=503, detail="No connector initialized")

    try:
        if hasattr(conn, 'get_latest_minutes'):
            minutes = await conn.get_latest_minutes()
            if not minutes:
                raise HTTPException(status_code=404, detail="No minutes found")

            save_minutes(minutes)
            if summarizer:
                await _auto_summarize_minutes(minutes)

            return {
                "minutes": minutes,
                "summary": get_minutes_summary(minutes.id),
            }
        else:
            raise HTTPException(status_code=400, detail="Connector does not support fetching latest")
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
            detail="LLM summarizer not available. Set GROK_API_KEY environment variable.",
        )

    existing = get_minutes_summary(request.minutes_id)
    if existing:
        return existing

    minutes = get_minutes(request.minutes_id)
    if not minutes:
        conn = _get_connector()
        if not conn:
            raise HTTPException(status_code=503, detail="Connector not initialized")
        try:
            if hasattr(conn, 'get_latest_minutes'):
                latest = await conn.get_latest_minutes()
                if latest and latest.id == request.minutes_id:
                    minutes = latest
                    save_minutes(minutes)
                else:
                    raise HTTPException(status_code=404, detail=f"Minutes {request.minutes_id} not found")
            else:
                raise HTTPException(status_code=404, detail=f"Minutes {request.minutes_id} not found")
        except HTTPException:
            raise
        except Exception as e:
            raise HTTPException(status_code=502, detail=f"Failed to fetch minutes: {str(e)}")

    try:
        image_fetcher = None
        has_urls = (
            minutes.page_image_urls
            and isinstance(minutes.page_image_urls[0], str)
            and minutes.document_url
        )
        if has_urls:
            _page_urls = list(minutes.page_image_urls)
            # Try to find a connector with fetch_page_images
            for city_key, conn in connectors.items():
                if hasattr(conn, 'fetch_page_images'):
                    image_fetcher = lambda: conn.fetch_page_images(
                        minutes.document_url, page_urls=_page_urls
                    )
                    break

        summary = await summarizer.summarize_minutes(
            minutes,
            image_fetcher=image_fetcher,
        )
        save_minutes_summary(minutes.id, summary)
        save_minutes(minutes)
        return summary
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Summarization failed: {str(e)}")


# --- Seed Endpoint ---

class SeedRequest(BaseModel):
    """Request to seed pre-computed minutes + summary data."""
    minutes_id: str
    title: str
    meeting_date: str
    meeting_type: str = "City Council Meeting"
    url: str
    document_url: Optional[str] = None
    raw_text: Optional[str] = None
    page_image_urls: list[str] = Field(default_factory=list)
    city: str = "Paris"
    state: str = "TX"
    source: str = "laserfiche"
    summary_text: str = ""
    key_decisions: list[dict] = Field(default_factory=list)
    budget_items: list[dict] = Field(default_factory=list)
    public_comment_opportunities: list[dict] = Field(default_factory=list)
    items: list[dict] = Field(default_factory=list)
    big_picture: str = ""
    what_you_can_do: list[dict] = Field(default_factory=list)


@app.post("/api/minutes/seed")
async def seed_minutes(request: SeedRequest):
    """Seed pre-computed minutes + summary data into the database."""
    try:
        minutes = Minutes(
            id=request.minutes_id,
            city=request.city,
            state=request.state,
            meeting_date=datetime.fromisoformat(request.meeting_date),
            meeting_type=request.meeting_type,
            title=request.title,
            url=request.url,
            document_url=request.document_url,
            raw_text=request.raw_text,
            page_image_urls=request.page_image_urls,
            source=request.source,
        )
        save_minutes(minutes)

        summary = SummaryResponse(
            minutes_id=request.minutes_id,
            meeting_date=minutes.meeting_date,
            meeting_type=minutes.meeting_type,
            summary=request.summary_text,
            key_decisions=request.key_decisions,
            budget_items=request.budget_items,
            public_comment_opportunities=request.public_comment_opportunities,
            items=request.items,
            big_picture=request.big_picture,
            what_you_can_do=request.what_you_can_do,
        )
        save_minutes_summary(request.minutes_id, summary)

        return {
            "status": "ok",
            "minutes_id": request.minutes_id,
            "summary_saved": bool(request.summary_text),
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Seed failed: {str(e)}")


# --- City Configuration ---

@app.get("/api/config")
async def get_config():
    """Get the current default city configuration."""
    cities_db = _load_cities_db()
    default_id = cities_db.get("default_city", "paris-tx")
    default_city = None
    for c in cities_db.get("cities", []):
        if c["id"] == default_id:
            default_city = c
            break
    if not default_city and cities_db.get("cities"):
        default_city = cities_db["cities"][0]

    return {
        "city": (default_city or {}).get("name", "Paris"),
        "state": (default_city or {}).get("state", "TX"),
        "website": (default_city or {}).get("website_url", ""),
        "agenda_center": (default_city or {}).get("agenda_center_url", ""),
        "laserfiche": (default_city or {}).get("laserfiche_url", ""),
        "connector_type": (default_city or {}).get("connector_type", "laserfiche"),
        "all_cities": [
            {"id": c["id"], "name": c["name"], "state": c["state"],
             "connector_type": c.get("connector_type")}
            for c in cities_db.get("cities", [])
        ],
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
    return await _detect_city_from_ip(request)


# --- City-specific endpoints ---

@app.get("/api/cities/{city_id}/minutes")
async def list_city_minutes(
    city_id: str,
    limit: int = Query(10, ge=1, le=50),
):
    """List recent minutes for a specific city."""
    conn = _get_connector(city_id)
    if not conn:
        raise HTTPException(status_code=404, detail=f"City '{city_id}' not found or inactive")

    city_name = city_id.replace("-", " ").title()
    for key, cfg in city_configs.items():
        if key.replace(" ", "-") == city_id.lower() or key.startswith(city_id.lower()):
            city_name = f"{cfg.name}, {cfg.state}"
            break

    try:
        if hasattr(conn, 'list_minutes'):
            minutes_list = await conn.list_minutes(limit=limit)
            enriched = _get_minutes_for_city(minutes_list, city_name)
            return {"minutes": enriched, "city": city_name, "city_id": city_id}
        else:
            return {"minutes": [], "city": city_name, "city_id": city_id}
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Failed to fetch minutes: {str(e)}")