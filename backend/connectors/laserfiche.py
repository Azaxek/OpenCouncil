"""
Laserfiche WebLink connector for Civic City Hub.

Paris, TX stores city council agendas in Laserfiche WebLink at
https://documents.paristexas.gov/weblink/. The system provides RSS feeds
for folder contents, which we use to discover agenda documents.

Folder structure (3 levels deep):
  City Council (5320)
    -> Agenda Packets (5321)
      -> 2026 (1395567), 2025 (1365526), 2024 (1341834), ...
        -> 05-11 (1402602), 04-27 (1401987), ...  (meeting subfolders)
          -> Agenda (docid)  (scanned document in Laserfiche)

RSS feed URL pattern:
  https://documents.paristexas.gov/WebLink/rss/dbid/0/folder/{folderId}/feed.rss

Document viewer URL pattern:
  https://documents.paristexas.gov/WebLink/docview.aspx?id={docId}&dbid=0

NOTE: Laserfiche stores documents as scanned images (TIFF), not text PDFs.
The docview.aspx returns an HTML viewer page. For text extraction, use
GPT-4o Vision on the viewer page or OCR on the rendered page images.
"""

import hashlib
import re
import uuid
from datetime import datetime, timezone
from typing import Optional
from xml.etree import ElementTree as ET

import httpx

from models.schemas import Agenda, AgendaItem, Minutes


def _make_agenda_id(meeting_date: Optional[datetime], title: str) -> str:
    """Generate a deterministic agenda ID from meeting date and title.
    
    This ensures the same agenda always gets the same ID, even across
    repeated fetch_agenda_list() calls. Uses first 8 chars of SHA-256 hash.
    """
    key = f"{meeting_date.isoformat() if meeting_date else 'unknown'}|{title}"
    return hashlib.sha256(key.encode()).hexdigest()[:8]

# Laserfiche folder IDs for Paris, TX
LASERFICHE_BASE = "https://documents.paristexas.gov/WebLink"
CITY_COUNCIL_FOLDER_ID = "5320"
AGENDA_PACKETS_FOLDER_ID = "5321"
MINUTES_FOLDER_ID = "20"
DBID = "0"


class LaserficheConnector:
    """Connector for Laserfiche WebLink document management systems.

    Discovers city council agendas via RSS feeds and provides
    viewer URLs for the scanned document pages.

    The folder structure is 3 levels deep:
      Agenda Packets (5321) -> Year (2026) -> Meeting (05-11) -> Document
    """

    def __init__(self, city: str = "Paris", state: str = "TX"):
        self.city = city
        self.state = state
        self.base_url = LASERFICHE_BASE
        self.client = httpx.AsyncClient(
            timeout=30.0,
            follow_redirects=True,
            cookies={},
            headers={
                "User-Agent": (
                    "CivicCityHub/1.0 (civic research project; "
                    "contact@civiccityhub.org)"
                ),
            },
        )

    async def close(self):
        await self.client.aclose()

    def _rss_url(self, folder_id: str) -> str:
        """Build the RSS feed URL for a given folder."""
        return (
            f"{self.base_url}/rss/dbid/{DBID}/folder/{folder_id}/feed.rss"
        )

    def _document_viewer_url(self, doc_id: str) -> str:
        """Build the document viewer URL for a given document ID.

        Laserfiche docview.aspx returns an HTML page with a JavaScript
        image viewer. This is the URL users visit to view the document.
        """
        return f"{self.base_url}/docview.aspx?id={doc_id}&dbid={DBID}"

    async def _fetch_rss(self, folder_id: str) -> list[dict]:
        """Fetch and parse an RSS feed from Laserfiche.

        Returns a list of items, each with title, link, pub_date,
        is_folder, is_document, and entity_id.
        """
        url = self._rss_url(folder_id)
        response = await self.client.get(url)
        response.raise_for_status()

        items = []
        try:
            root = ET.fromstring(response.content)
            for item_elem in root.iter("item"):
                title_el = item_elem.find("title")
                link_el = item_elem.find("link")
                pub_date_el = item_elem.find("pubDate")
                desc_el = item_elem.find("description")

                title = title_el.text.strip() if title_el is not None else ""
                link = link_el.text.strip() if link_el is not None else ""
                pub_date_str = (
                    pub_date_el.text.strip()
                    if pub_date_el is not None
                    else ""
                )
                description = (
                    desc_el.text.strip() if desc_el is not None else ""
                )

                # Determine if this is a folder or a document
                is_folder = "browse.aspx" in link
                is_document = "docview.aspx" in link

                # Extract startid from browse links, or id from docview links
                entity_id = None
                if is_folder:
                    match = re.search(r"startid=(\d+)", link)
                    if match:
                        entity_id = match.group(1)
                elif is_document:
                    match = re.search(r"id=(\d+)", link)
                    if match:
                        entity_id = match.group(1)

                # Parse pubDate
                pub_date = None
                if pub_date_str:
                    try:
                        pub_date = datetime.strptime(
                            pub_date_str, "%a, %d %b %Y %H:%M:%S %Z"
                        )
                        pub_date = pub_date.replace(tzinfo=timezone.utc)
                    except ValueError:
                        pass

                items.append({
                    "title": title,
                    "link": link,
                    "pub_date": pub_date,
                    "is_folder": is_folder,
                    "is_document": is_document,
                    "entity_id": entity_id,
                    "description": description,
                })
        except ET.ParseError as e:
            print(f"[WARN] RSS parse error for folder {folder_id}: {e}")
            return []

        return items

    async def _get_current_year_folder_id(self) -> Optional[str]:
        """Find the folder ID for the current year's agenda packets."""
        items = await self._fetch_rss(AGENDA_PACKETS_FOLDER_ID)
        if not items:
            return None

        current_year = datetime.now(timezone.utc).year

        # Look for the current year folder
        for item in items:
            if item["is_folder"] and item["title"] == str(current_year):
                return item["entity_id"]

        # Fall back to the most recent year folder
        year_folders = []
        for item in items:
            if item["is_folder"] and item["title"].isdigit():
                year_folders.append((int(item["title"]), item["entity_id"]))

        if year_folders:
            year_folders.sort(key=lambda x: x[0], reverse=True)
            return year_folders[0][1]

        return None

    def _parse_date_from_meeting_title(self, title: str, year: int) -> Optional[datetime]:
        """Extract a date from a meeting subfolder title like '05-11' or '01-06 Workshop - CANCELLED'.

        The title contains MM-DD at the start. We combine with the given year.
        """
        if not title:
            return None

        # Match MM-DD at the start of the title
        match = re.match(r"(\d{1,2})-(\d{1,2})", title.strip())
        if match:
            try:
                month = int(match.group(1))
                day = int(match.group(2))
                if 1 <= month <= 12 and 1 <= day <= 31:
                    return datetime(year, month, day, tzinfo=timezone.utc)
            except ValueError:
                pass

        return None

    async def fetch_agenda_list(self, limit: int = 20) -> list[dict]:
        """Fetch the list of recent agenda documents from Laserfiche.

        Strategy (3 levels deep):
        1. Get the Agenda Packets folder contents (year subfolders)
        2. Find the current/most recent year folder
        3. Get the meeting subfolders from that year (e.g. "05-11", "04-27")
        4. For each meeting subfolder, get the actual document inside
        """
        year_folder_id = await self._get_current_year_folder_id()
        if not year_folder_id:
            print("[WARN] No year folder found in Agenda Packets")
            return []

        # Determine the year from the folder title
        year = datetime.now(timezone.utc).year

        # Fetch meeting subfolders from the year folder
        meeting_folders = await self._fetch_rss(year_folder_id)
        if not meeting_folders:
            return []

        # Filter to only folders (each meeting is a subfolder)
        meeting_folders = [m for m in meeting_folders if m["is_folder"]]

        # Sort by pub_date descending (most recent first)
        meeting_folders.sort(
            key=lambda m: m["pub_date"] or datetime.min.replace(tzinfo=timezone.utc),
            reverse=True,
        )

        # Limit how many meeting folders we'll process
        meeting_folders = meeting_folders[:limit]

        agendas = []
        for meeting in meeting_folders:
            # Fetch the contents of this meeting subfolder to find the document
            meeting_items = await self._fetch_rss(meeting["entity_id"])

            # Find the first document in this meeting folder
            doc = None
            for item in meeting_items:
                if item["is_document"]:
                    doc = item
                    break

            if not doc:
                continue

            # Parse meeting date from the folder title (e.g. "05-11" -> May 11)
            meeting_date = self._parse_date_from_meeting_title(
                meeting["title"], year
            )

            # Fall back to pubDate
            if not meeting_date and meeting["pub_date"]:
                meeting_date = meeting["pub_date"]

            document_url = (
                self._document_viewer_url(doc["entity_id"])
                if doc["entity_id"]
                else None
            )

            # Build a descriptive title
            title = meeting["title"]
            if "workshop" in title.lower():
                display_title = f"City Council Workshop - {title}"
            elif "special" in title.lower() or "called" in title.lower():
                display_title = f"Special City Council Meeting - {title}"
            else:
                display_title = f"City Council Meeting - {title}"

            agendas.append({
                "id": _make_agenda_id(meeting_date, display_title),
                "title": display_title,
                "meeting_date": meeting_date,
                "url": document_url,
                "document_url": document_url,
                "doc_id": doc["entity_id"],
                "pub_date": meeting["pub_date"],
                "meeting_folder_title": meeting["title"],
            })

        # Sort by date descending
        agendas.sort(
            key=lambda a: a["meeting_date"] or datetime.min.replace(tzinfo=timezone.utc),
            reverse=True,
        )

        return agendas[:limit]

    async def fetch_agenda_document_text(self, document_url: str) -> Optional[str]:
        """Attempt to extract text from a Laserfiche document.

        NOTE: Laserfiche stores documents as scanned images (TIFF).
        The docview.aspx returns an HTML viewer page, not a text PDF.

        This method returns the viewer URL for LLM Vision processing.
        When GPT-4o Vision is available, it can read the document
        directly from this URL.

        Returns the viewer URL as a fallback text representation.
        """
        if not document_url:
            return None

        try:
            response = await self.client.get(document_url)
            response.raise_for_status()

            # The response is HTML (viewer page), not a PDF
            # Return the URL for LLM Vision processing
            return (
                f"[This document is a scanned image available at: "
                f"{document_url}]"
            )
        except Exception as e:
            print(f"[WARN] Error accessing document viewer: {e}")
            return None

    def _parse_agenda_items_from_text(self, text: str) -> list[AgendaItem]:
        """Parse individual agenda items from raw text."""
        items = []
        if not text:
            return items

        section_patterns = [
            r"(CALL TO ORDER|ROLL CALL)",
            r"(PUBLIC COMMENT|CITIZEN PARTICIPATION|OPEN FORUM)",
            r"(CONSENT AGENDA|CONSENT ITEMS)",
            r"(PUBLIC HEARING)",
            r"(NEW BUSINESS|REGULAR BUSINESS|ACTION ITEMS)",
            r"(OLD BUSINESS|UNFINISHED BUSINESS)",
            r"(REPORTS|STAFF REPORTS|COMMITTEE REPORTS)",
            r"(EXECUTIVE SESSION|CLOSED SESSION)",
            r"(ADJOURNMENT)",
        ]

        current_section = "Preamble"
        lines = text.split("\n")

        for line in lines:
            line = line.strip()
            if not line:
                continue

            found_section = False
            for pattern in section_patterns:
                if re.search(pattern, line, re.IGNORECASE):
                    current_section = line
                    found_section = True
                    break

            if not found_section and len(line) > 10:
                items.append(AgendaItem(
                    title=line[:200],
                    description=line if len(line) > 200 else None,
                    category=current_section,
                ))

        return items

    async def get_latest_agenda(self) -> Optional[Agenda]:
        """Fetch the most recent city council agenda from Laserfiche."""
        agendas = await self.fetch_agenda_list(limit=5)
        if not agendas:
            return None

        latest = agendas[0]

        # Access the document viewer (returns HTML, not PDF text)
        raw_text = None
        if latest.get("document_url"):
            raw_text = await self.fetch_agenda_document_text(
                latest["document_url"]
            )

        # Parse items from text (will be minimal for scanned docs)
        items = self._parse_agenda_items_from_text(raw_text) if raw_text else []

        # Determine meeting type from title
        title_lower = (latest["title"] or "").lower()
        if "regular" in title_lower:
            meeting_type = "City Council Regular Meeting"
        elif "special" in title_lower or "called" in title_lower:
            meeting_type = "City Council Special Meeting"
        elif "workshop" in title_lower:
            meeting_type = "City Council Workshop"
        elif "executive" in title_lower:
            meeting_type = "Executive Session"
        else:
            meeting_type = "City Council Meeting"

        return Agenda(
            id=latest["id"],
            city=self.city,
            state=self.state,
            meeting_date=latest["meeting_date"] or datetime.now(timezone.utc),
            meeting_type=meeting_type,
            title=latest["title"],
            url=latest["url"] or "",
            pdf_url=latest.get("document_url"),
            document_url=latest.get("document_url"),
            items=items,
            raw_text=raw_text,
            source="laserfiche",
        )

    async def list_agendas(self, limit: int = 10) -> list[dict]:
        """List recent agendas with metadata (no full parsing)."""
        agendas = await self.fetch_agenda_list(limit=limit)
        return [
            {
                "id": a["id"],
                "title": a["title"],
                "meeting_date": (
                    a["meeting_date"].isoformat()
                    if a["meeting_date"]
                    else None
                ),
                "url": a["url"],
                "document_url": a["document_url"],
            }
            for a in agendas
        ]

    # ──────────────────────────────────────────
    # Minutes (official records of what happened)
    # ──────────────────────────────────────────

    async def _get_current_year_minutes_folder_id(self) -> Optional[str]:
        """Find the folder ID for the current year's minutes.

        Minutes folder structure:
          Minutes (20) -> Year (e.g. 2026, id=1396340) -> Documents directly
        """
        items = await self._fetch_rss(MINUTES_FOLDER_ID)
        if not items:
            return None

        current_year = datetime.now(timezone.utc).year

        # Look for the current year folder
        for item in items:
            if item["is_folder"] and item["title"] == str(current_year):
                return item["entity_id"]

        # Fall back to the most recent year folder
        year_folders = []
        for item in items:
            if item["is_folder"] and item["title"].isdigit():
                year_folders.append((int(item["title"]), item["entity_id"]))

        if year_folders:
            year_folders.sort(key=lambda x: x[0], reverse=True)
            return year_folders[0][1]

        return None

    def _parse_date_from_minutes_title(self, title: str) -> Optional[datetime]:
        """Extract a date from a minutes document title like '01-12-2026'.

        Minutes documents are named by date (MM-DD-YYYY) directly.
        """
        if not title:
            return None

        # Match MM-DD-YYYY
        match = re.match(r"(\d{1,2})-(\d{1,2})-(\d{4})", title.strip())
        if match:
            try:
                month = int(match.group(1))
                day = int(match.group(2))
                year = int(match.group(3))
                if 1 <= month <= 12 and 1 <= day <= 31:
                    return datetime(year, month, day, tzinfo=timezone.utc)
            except ValueError:
                pass

        return None

    async def fetch_minutes_list(self, limit: int = 20) -> list[dict]:
        """Fetch the list of recent minutes documents from Laserfiche.

        Minutes are stored directly in year folders (no subfolders):
          Minutes (20) -> 2026 (1396340) -> 01-12-2026 (doc), 01-28-2026 (doc), ...
        """
        year_folder_id = await self._get_current_year_minutes_folder_id()
        if not year_folder_id:
            print("[WARN] No year folder found in Minutes")
            return []

        # Fetch documents from the year folder
        documents = await self._fetch_rss(year_folder_id)
        if not documents:
            return []

        # Filter to only documents (not subfolders)
        documents = [d for d in documents if d["is_document"]]

        # Sort by pub_date descending (most recent first)
        documents.sort(
            key=lambda d: d["pub_date"] or datetime.min.replace(tzinfo=timezone.utc),
            reverse=True,
        )

        # Limit
        documents = documents[:limit]

        minutes_list = []
        for doc in documents:
            # Parse meeting date from the document title (e.g. "01-12-2026")
            meeting_date = self._parse_date_from_minutes_title(doc["title"])

            # Fall back to pubDate
            if not meeting_date and doc["pub_date"]:
                meeting_date = doc["pub_date"]

            document_url = (
                self._document_viewer_url(doc["entity_id"])
                if doc["entity_id"]
                else None
            )

            # Build a descriptive title
            title = doc["title"]
            display_title = f"City Council Meeting Minutes - {title}"

            minutes_list.append({
                "id": str(uuid.uuid4())[:8],
                "title": display_title,
                "meeting_date": meeting_date,
                "url": document_url,
                "document_url": document_url,
                "doc_id": doc["entity_id"],
                "pub_date": doc["pub_date"],
            })

        # Sort by date descending
        minutes_list.sort(
            key=lambda m: m["meeting_date"] or datetime.min.replace(tzinfo=timezone.utc),
            reverse=True,
        )

        return minutes_list[:limit]

    async def get_latest_minutes(self) -> Optional[Minutes]:
        """Fetch the most recent city council minutes from Laserfiche."""
        minutes_list = await self.fetch_minutes_list(limit=5)
        if not minutes_list:
            return None

        latest = minutes_list[0]

        # Access the document viewer (returns HTML, not PDF text)
        raw_text = None
        if latest.get("document_url"):
            raw_text = await self.fetch_agenda_document_text(
                latest["document_url"]
            )

        # Determine meeting type from title
        title_lower = (latest["title"] or "").lower()
        if "regular" in title_lower:
            meeting_type = "City Council Regular Meeting"
        elif "special" in title_lower or "called" in title_lower:
            meeting_type = "City Council Special Meeting"
        elif "workshop" in title_lower:
            meeting_type = "City Council Workshop"
        elif "executive" in title_lower:
            meeting_type = "Executive Session"
        else:
            meeting_type = "City Council Meeting"

        return Minutes(
            id=latest["id"],
            city=self.city,
            state=self.state,
            meeting_date=latest["meeting_date"] or datetime.now(timezone.utc),
            meeting_type=meeting_type,
            title=latest["title"],
            url=latest["url"] or "",
            document_url=latest.get("document_url"),
            raw_text=raw_text,
            source="laserfiche",
        )

    async def list_minutes(self, limit: int = 10) -> list[dict]:
        """List recent minutes with metadata (no full parsing)."""
        minutes_list = await self.fetch_minutes_list(limit=limit)
        return [
            {
                "id": m["id"],
                "title": m["title"],
                "meeting_date": (
                    m["meeting_date"].isoformat()
                    if m["meeting_date"]
                    else None
                ),
                "url": m["url"],
                "document_url": m["document_url"],
            }
            for m in minutes_list
        ]
