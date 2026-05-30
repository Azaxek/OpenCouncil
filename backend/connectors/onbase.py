"""
OnBase Agenda Online connector for OpenCouncil.
Handles cities using Hyland OnBase Agenda Online (e.g., Frisco, TX).

Works by scraping the OnBase Agenda Online web interface.
PDFs are accessible via the OnBase document viewer.
"""
import hashlib
import re
from datetime import datetime, timezone
from typing import Optional

import httpx
from bs4 import BeautifulSoup

from models.schemas import Minutes


# Category IDs for Frisco (discovered from the OnBase page)
CATEGORIES = {
    "105": "City Council",
    "103": "Boards & Commissions",
    "104": "Planning & Zoning",
}


class OnBaseConnector:
    """Connector for Hyland OnBase Agenda Online.

    Configuration:
      - base_url: The OnBase Agenda Online root (e.g., https://agenda.friscotexas.gov/OnBaseAgendaOnline)
      - city: City name
      - state: State code
      - category_id: The OnBase category ID for city council meetings
    """

    def __init__(
        self,
        base_url: str = "https://agenda.friscotexas.gov/OnBaseAgendaOnline",
        city: str = "Frisco",
        state: str = "TX",
        category_id: str = "105",
    ):
        self.base_url = base_url.rstrip("/")
        self.city = city
        self.state = state
        self.category_id = category_id
        self.client = httpx.AsyncClient(
            timeout=30.0,
            follow_redirects=True,
            verify=False,
            headers={
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/120.0.0.0 Safari/537.36"
                ),
            },
        )

    async def close(self):
        await self.client.aclose()

    async def _get_request_token(self) -> str:
        """Fetch the search page and extract the __RequestVerificationToken."""
        try:
            r = await self.client.get(f"{self.base_url}/Meetings")
            r.raise_for_status()
            soup = BeautifulSoup(r.text, 'html.parser')
            token_input = soup.find('input', {'name': '__RequestVerificationToken'})
            return token_input.get('value', '') if token_input else ''
        except Exception as e:
            print(f"[OnBase] Failed to get request token: {e}")
            return ''

    async def fetch_minutes_list(self, limit: int = 20) -> list[dict]:
        """Search OnBase for meetings and extract metadata."""
        token = await self._get_request_token()
        if not token:
            print("[OnBase] No request token available")
            return []

        try:
            # POST search with category filter
            r = await self.client.post(
                f"{self.base_url}/Meetings",
                data={
                    "__RequestVerificationToken": token,
                    "CategoryId": self.category_id,
                    "Keywords": "",
                },
            )
            r.raise_for_status()
        except Exception as e:
            print(f"[OnBase] Failed to search meetings: {e}")
            return []

        soup = BeautifulSoup(r.text, 'html.parser')

        # Parse meeting list from the results
        meetings = []
        
        # OnBase renders meetings in a specific table/list structure
        # Look for meeting cards/rows
        meeting_elems = soup.select('.meeting-item, .meeting-card, [class*="meeting"]')
        
        # Also try to find meeting links
        meeting_links = soup.find_all('a', href=re.compile(r'/OnBaseAgendaOnline/Meeting/\d+'))
        
        for link in meeting_links:
            href = link.get('href', '')
            text = link.get_text(strip=True)
            
            # Extract meeting ID from URL
            match = re.search(r'/Meeting/(\d+)', href)
            meeting_id = match.group(1) if match else None
            if not meeting_id:
                continue

            full_url = f"{self.base_url}{href}" if href.startswith('/') else href
            
            # Parse date and type from the text
            # Common formats: "City Council Regular Meeting - 05/06/2026" or similar
            date_match = re.search(r'(\d{1,2})[/-](\d{1,2})[/-](\d{2,4})', text)
            meeting_date = None
            if date_match:
                try:
                    month, day, year = int(date_match.group(1)), int(date_match.group(2)), int(date_match.group(3))
                    if year < 100:
                        year += 2000
                    meeting_date = datetime(year, month, day, tzinfo=timezone.utc)
                except ValueError:
                    pass

            # Determine meeting type
            meeting_type = "City Council Meeting"
            text_lower = text.lower()
            if "regular" in text_lower:
                meeting_type = "City Council Regular Meeting"
            elif "special" in text_lower:
                meeting_type = "City Council Special Meeting"
            elif "workshop" in text_lower or "retreat" in text_lower:
                meeting_type = "City Council Workshop"

            stable_id = hashlib.md5(full_url.encode()).hexdigest()[:8]

            meetings.append({
                "id": stable_id,
                "title": text or f"City Council Meeting - {meeting_date.strftime('%m-%d-%Y') if meeting_date else 'Unknown'}",
                "meeting_date": meeting_date or datetime.now(timezone.utc),
                "url": full_url,
                "document_url": full_url,
                "meeting_type": meeting_type,
                "meeting_id": meeting_id,
            })

        # Sort by date descending
        meetings.sort(
            key=lambda m: m["meeting_date"] or datetime.min.replace(tzinfo=timezone.utc),
            reverse=True,
        )

        # Only return recent meetings (current year and previous year)
        now = datetime.now(timezone.utc)
        current_year = now.year
        meetings = [m for m in meetings if m["meeting_date"] and m["meeting_date"].year >= current_year - 1]

        return meetings[:limit]

    async def fetch_document_text(self, document_url: str) -> Optional[str]:
        """Return placeholder — OnBase documents are handled via their viewer."""
        return f"[This document is available in OnBase at: {document_url}]"

    async def fetch_page_image_urls(self, document_url: str) -> list[str]:
        """OnBase documents may have PDF downloads available."""
        return [document_url]

    async def fetch_page_images(self, document_url: str, page_urls: Optional[list[str]] = None) -> list[bytes]:
        """Download a PDF from OnBase and render its pages to PNG images for OCR processing.
        
        Uses PyMuPDF (fitz) if available to render PDF pages at 300 DPI.
        Falls back to returning empty list if PyMuPDF is not installed.
        """
        urls = page_urls or [document_url]
        images: list[bytes] = []
        
        for url in urls:
            try:
                response = await self.client.get(url)
                response.raise_for_status()
                pdf_bytes = response.content
                
                if pdf_bytes[:4] != b'%PDF':
                    print(f"[OnBase] URL {url} is not a valid PDF")
                    continue
                
                try:
                    import fitz
                    pdf_doc = fitz.open(stream=pdf_bytes, filetype="pdf")
                    zoom = 300 / 72
                    mat = fitz.Matrix(zoom, zoom)
                    
                    for page_num in range(len(pdf_doc)):
                        page = pdf_doc[page_num]
                        pix = page.get_pixmap(matrix=mat)
                        img_bytes = pix.tobytes("png")
                        if img_bytes:
                            images.append(img_bytes)
                            print(f"[OnBase] Rendered page {page_num + 1}: {len(img_bytes)} bytes")
                    
                    pdf_doc.close()
                    print(f"[OnBase] Total: {len(images)} pages from PDF")
                except ImportError:
                    print("[OnBase] PyMuPDF (fitz) not installed, cannot render PDF pages")
                    return []
                except Exception as e:
                    print(f"[OnBase] PDF rendering failed: {e}")
                    return []
            except Exception as e:
                print(f"[OnBase] Failed to download PDF from {url}: {e}")
                continue
        
        return images

    async def get_latest_minutes(self) -> Optional[Minutes]:
        """Fetch the most recent meeting."""
        minutes_list = await self.fetch_minutes_list(limit=5)
        if not minutes_list:
            return None

        latest = minutes_list[0]
        return Minutes(
            id=latest["id"],
            city=self.city,
            state=self.state,
            meeting_date=latest["meeting_date"] or datetime.now(timezone.utc),
            meeting_type=latest.get("meeting_type", "City Council Meeting"),
            title=latest["title"],
            url=latest["url"],
            document_url=latest.get("document_url"),
            raw_text=await self.fetch_document_text(latest["url"]),
            page_image_urls=await self.fetch_page_image_urls(latest["url"]),
            source="onbase",
        )

    async def list_minutes(self, limit: int = 10) -> list[dict]:
        """List recent meetings with metadata."""
        minutes_list = await self.fetch_minutes_list(limit=limit)
        return [
            {
                "id": m["id"],
                "title": m["title"],
                "meeting_date": m["meeting_date"].isoformat() if m["meeting_date"] else None,
                "url": m["url"],
                "document_url": m["document_url"],
            }
            for m in minutes_list
        ]