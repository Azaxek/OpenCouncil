"""
Generic PDF connector for OpenCouncil.
Handles cities that publish PDF meeting agendas/minutes on a custom CMS page
(e.g., Revize CMS) without a structured API.

Works by:
1. Fetching the city council page
2. Parsing all PDF links with agenda/minutes context
3. Sorting by date using filename patterns
"""
import hashlib
import re
from datetime import datetime, timezone
from typing import Optional
from urllib.parse import urljoin

import httpx
from bs4 import BeautifulSoup

from models.schemas import Minutes


class GenericPDFConnector:
    """Connector for cities that publish PDF agendas/minutes on a page.

    Configuration:
      - council_url: URL of the page listing all agenda/minutes PDFs
      - city: City name
      - state: State code
      - name_pattern: Optional regex to filter relevant PDF links
    """

    def __init__(
        self,
        council_url: str,
        city: str = "Sulphur Springs",
        state: str = "TX",
        name_pattern: Optional[str] = None,
    ):
        self.council_url = council_url.rstrip("/")
        self.city = city
        self.state = state
        self.name_pattern = name_pattern
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

    def _infer_date_from_filename(self, filename: str) -> Optional[datetime]:
        """Extract date from common PDF naming patterns."""
        fname = filename.split("?")[0].split("/")[-1]  # Strip query params, get filename

        def _validate_date(year: int, month: int, day: int) -> Optional[datetime]:
            """Return datetime if valid, None otherwise. Year should be 2000-2030."""
            try:
                if 2000 <= year <= 2030 and 1 <= month <= 12 and 1 <= day <= 31:
                    return datetime(year, month, day, tzinfo=timezone.utc)
            except (ValueError, OverflowError):
                pass
            return None

        # 1. Try SKM pattern first: SKM_CxxxYYMMDD...
        #    SKM_C551i25123014380 -> year=25 month=12 day=30
        m = re.search(r'SKM_C\w*?(\d{2})(\d{2})(\d{2})', fname)
        if m:
            yr = 2000 + int(m.group(1))
            dt = _validate_date(yr, int(m.group(2)), int(m.group(3)))
            if dt:
                return dt

        # 2. Try YYYYMMDD pattern (prefer this for standard names like 20260602A.pdf)
        m = re.search(r'(?:^|_|[^\d])(\d{4})(\d{2})(\d{2})(?:[^\d]|$)', fname)
        if m:
            dt = _validate_date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
            if dt:
                return dt

        # 3. Try Month-Day-Year patterns like 01_16_24, 02012022A, 12062022M
        m = re.search(r'(?:^|[^\d])(\d{1,2})[_-](\d{1,2})[_-](\d{4})(?:[^\d]|$)', fname)
        if m:
            dt = _validate_date(int(m.group(3)), int(m.group(1)), int(m.group(2)))
            if dt:
                return dt

        return None

    def _infer_meeting_type(self, text: str, filename: str) -> str:
        """Determine meeting type from link text and filename."""
        combined = f"{text} {filename}".lower()
        if "special" in combined or "executive" in combined:
            return "City Council Special Meeting"
        if "workshop" in combined or "retreat" in combined or "budget" in combined:
            return "City Council Workshop"
        if "regular" in combined or "minute" in combined:
            return "City Council Regular Meeting"
        return "City Council Meeting"

    def _is_agenda(self, text: str, filename: str) -> bool:
        """Check if the PDF is an agenda (vs minutes).

        Returns True if agenda, False if minutes.
        """
        combined = f"{text} {filename}".lower()
        fname = filename.split("?")[0].split("/")[-1]

        # Filename pattern check: A.pdf suffix = agenda, M.pdf suffix = minutes
        if re.search(r'A\d{0,2}\.pdf', fname):
            return True
        if re.search(r'M\d{0,2}\.pdf', fname):
            return False

        # Text keyword check
        if "minute" in combined or "min" in fname.lower()[:5]:
            return False
        if "agenda" in combined:
            return True

        # Default: assume minutes (we prefer to include rather than exclude)
        return False

    async def fetch_minutes_list(self, limit: int = 50) -> list[dict]:
        """Parse the council page and extract PDF metadata.

        Returns up to `limit` unique meeting entries sorted by date descending.
        """
        try:
            response = await self.client.get(self.council_url)
            response.raise_for_status()
        except Exception as e:
            print(f"[GenericPDF] Failed to fetch {self.council_url}: {e}")
            return []

        soup = BeautifulSoup(response.text, 'html.parser')
        links = soup.find_all('a', href=True)

        doc_links = []
        for a in links:
            href = a.get('href', '')
            text = a.get_text(strip=True)

            # Only process PDFs
            if not (href.endswith('.pdf') or '.pdf?' in href):
                continue

            # Resolve relative URLs using proper urljoin
            resolved_url = urljoin(self.council_url, href)

            # Only council/agenda/minutes related
            if not any(kw in text.lower() for kw in ['council', 'agenda', 'minute', 'meeting', 'regular', 'special', 'workshop', 'retreat']):
                continue

            meeting_date = self._infer_date_from_filename(resolved_url)
            if not meeting_date:
                continue

            meeting_type = self._infer_meeting_type(text, resolved_url)
            is_agenda = self._is_agenda(text, resolved_url)

            # Build descriptive title
            if text:
                title = text
            else:
                title = f"City Council {'Agenda' if is_agenda else 'Minutes'} - {meeting_date.strftime('%m-%d-%Y')}"

            # Generate stable ID from URL
            stable_id = hashlib.md5(resolved_url.encode()).hexdigest()[:8]

            doc_links.append({
                "id": stable_id,
                "title": title,
                "city": self.city,
                "state": self.state,
                "meeting_date": meeting_date,
                "url": resolved_url,
                "document_url": resolved_url,
                "meeting_type": meeting_type,
                "is_agenda": is_agenda,
            })

        # Sort by date descending
        doc_links.sort(
            key=lambda d: (
                d["meeting_date"] or datetime.min.replace(tzinfo=timezone.utc),
                0 if d["is_agenda"] else 1,  # agendas first on same date
            ),
            reverse=True,
        )

        # Deduplicate by date — only keep the most recent item per date (prefer agenda)
        seen_dates = set()
        unique = []
        for d in doc_links:
            date_key = d["meeting_date"].strftime("%Y%m%d") if d["meeting_date"] else ""
            if date_key not in seen_dates:
                seen_dates.add(date_key)
                unique.append(d)

        # Only return recent meetings (current year and previous year)
        now = datetime.now(timezone.utc)
        current_year = now.year
        recent = [m for m in unique if m["meeting_date"] and m["meeting_date"].year >= current_year - 1]

        # Filter to ONLY minutes — exclude agendas
        minutes_only = [m for m in recent if not m.get("is_agenda", False)]

        return minutes_only[:limit]

    async def fetch_document_text(self, document_url: str) -> Optional[str]:
        """Return placeholder — PDFs are handled by OCR pipeline."""
        return f"[This document is a PDF available at: {document_url}]"

    async def fetch_page_image_urls(self, document_url: str) -> list[str]:
        """PDFs can be downloaded directly, return URL for OCR pipeline."""
        return [document_url]

    async def fetch_page_images(self, document_url: str, page_urls: Optional[list[str]] = None) -> list[bytes]:
        """Download a PDF and render its pages to PNG images for OCR processing.
        
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
                    print(f"[GenericPDF] URL {url} is not a valid PDF")
                    continue
                
                try:
                    import fitz
                    pdf_doc = fitz.open(stream=pdf_bytes, filetype="pdf")
                    zoom = 300 / 72  # 300 DPI
                    mat = fitz.Matrix(zoom, zoom)
                    
                    for page_num in range(len(pdf_doc)):
                        page = pdf_doc[page_num]
                        pix = page.get_pixmap(matrix=mat)
                        img_bytes = pix.tobytes("png")
                        if img_bytes:
                            images.append(img_bytes)
                            print(f"[GenericPDF] Rendered page {page_num + 1}: {len(img_bytes)} bytes")
                    
                    pdf_doc.close()
                    print(f"[GenericPDF] Total: {len(images)} pages from PDF")
                except ImportError:
                    print("[GenericPDF] PyMuPDF (fitz) not installed, cannot render PDF pages")
                    print("       Install with: pip install PyMuPDF")
                    return []
                except Exception as e:
                    print(f"[GenericPDF] PDF rendering failed: {e}")
                    return []
            except Exception as e:
                print(f"[GenericPDF] Failed to download PDF from {url}: {e}")
                continue
        
        return images

    async def get_latest_minutes(self) -> Optional[Minutes]:
        """Fetch the most recent minutes."""
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
            source="generic_pdf",
        )

    async def list_minutes(self, limit: int = 10) -> list[dict]:
        """List recent minutes with metadata."""
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