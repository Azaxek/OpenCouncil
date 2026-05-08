"""
CivicPlus connector for Civic City Hub.

Scrapes city council agendas from CivicPlus-powered municipal websites.
Paris, TX uses CivicPlus (https://www.paristexas.gov) with Laserfiche
for document storage (https://documents.paristexas.gov/weblink/).

Strategy:
1. Fetch the AgendaCenter page to get the list of recent agendas
2. Parse the HTML to extract agenda metadata (date, type, PDF links)
3. Download PDFs and extract text
4. Return structured Agenda objects

For cities using CivicPlus, the agenda data is loaded dynamically via
JavaScript. We use the /AgendaCenter/Search/ endpoint or parse the
server-rendered HTML from the UpdateCategoryList POST endpoint.
"""

import re
import uuid
from datetime import datetime
from typing import Optional

import httpx
from bs4 import BeautifulSoup

from models.schemas import Agenda, AgendaItem

# Use html.parser instead of lxml to avoid build issues on Python 3.14+
PARSER = "html.parser"


class CivicPlusConnector:
    """Connector for CivicPlus-powered city websites."""

    def __init__(self, base_url: str, city: str = "Paris", state: str = "TX"):
        self.base_url = base_url.rstrip("/")
        self.city = city
        self.state = state
        self.client = httpx.AsyncClient(
            timeout=30.0,
            follow_redirects=True,
            headers={
                "User-Agent": "CivicCityHub/1.0 (civic research project; contact@civiccityhub.org)",
            },
        )

    async def close(self):
        await self.client.aclose()

    async def fetch_agenda_list(self, category_id: str = "1") -> list[dict]:
        """
        Fetch the list of recent agendas from the AgendaCenter.
        
        CivicPlus loads agendas dynamically. We hit the UpdateCategoryList
        endpoint which returns HTML with the agenda table.
        """
        url = f"{self.base_url}/AgendaCenter/UpdateCategoryList"
        data = {
            "CIDs": f"City-Council-Meetings-Regular-{category_id}",
            "startDate": "",
            "endDate": "",
            "dateRange": "",
            "dateSelector": "",
            "term": "",
        }
        response = await self.client.post(url, data=data)
        response.raise_for_status()

        soup = BeautifulSoup(response.text, PARSER)
        agendas = []

        # Look for agenda rows in the table
        for row in soup.select("tr.catAgendaRow, tr[class*='agenda']"):
            cells = row.find_all("td")
            if len(cells) < 2:
                continue

            date_cell = cells[0]
            title_cell = cells[1]

            # Extract date
            date_text = date_cell.get_text(strip=True)
            meeting_date = self._parse_date(date_text)

            # Extract title and links
            title_link = title_cell.find("a")
            title = title_link.get_text(strip=True) if title_link else "City Council Meeting"

            # Extract agenda URL
            agenda_url = None
            pdf_url = None
            if title_link and title_link.get("href"):
                href = title_link["href"]
                agenda_url = f"{self.base_url}{href}" if href.startswith("/") else href

            # Look for PDF links
            for link in title_cell.find_all("a"):
                href = link.get("href", "")
                if ".pdf" in href.lower() or "agenda" in href.lower():
                    pdf_url = href if href.startswith("http") else f"{self.base_url}{href}"
                    if "agenda" in link.get_text(strip=True).lower():
                        break

            agendas.append({
                "id": str(uuid.uuid4())[:8],
                "title": title,
                "meeting_date": meeting_date,
                "url": agenda_url,
                "pdf_url": pdf_url,
            })

        return agendas

    async def fetch_agenda_detail(self, agenda_url: str) -> Optional[str]:
        """
        Fetch the detail page for a specific agenda to get more metadata
        and the actual PDF/document links.
        """
        try:
            response = await self.client.get(agenda_url)
            response.raise_for_status()
            soup = BeautifulSoup(response.text, "lxml")

            # Extract document links
            documents = []
            for link in soup.find_all("a", href=True):
                href = link["href"]
                if ".pdf" in href.lower():
                    full_url = href if href.startswith("http") else f"{self.base_url}{href}"
                    documents.append(full_url)

            return "\n".join(documents)
        except Exception as e:
            print(f"Error fetching agenda detail: {e}")
            return None

    async def fetch_agenda_pdf_text(self, pdf_url: str) -> Optional[str]:
        """
        Download a PDF agenda and extract its text content.
        Falls back to returning the URL if PDF parsing fails.
        """
        try:
            response = await self.client.get(pdf_url)
            response.raise_for_status()

            # Try to extract text from PDF
            try:
                import io
                from PyPDF2 import PdfReader

                pdf_file = io.BytesIO(response.content)
                reader = PdfReader(pdf_file)
                text_parts = []
                for page in reader.pages:
                    text = page.extract_text()
                    if text:
                        text_parts.append(text)
                return "\n\n".join(text_parts)
            except ImportError:
                print("PyPDF2 not available, returning URL instead")
                return f"[PDF available at: {pdf_url}]"
            except Exception as e:
                print(f"PDF parsing error: {e}")
                return f"[PDF available at: {pdf_url}]"

        except Exception as e:
            print(f"Error downloading PDF: {e}")
            return None

    def _parse_date(self, date_text: str) -> Optional[datetime]:
        """Parse date string from CivicPlus agenda listing."""
        if not date_text:
            return None

        # Try common formats
        formats = [
            "%m/%d/%Y",
            "%B %d, %Y",
            "%b %d, %Y",
            "%Y-%m-%d",
        ]
        for fmt in formats:
            try:
                return datetime.strptime(date_text.strip(), fmt)
            except ValueError:
                continue
        return None

    def _parse_agenda_items_from_text(self, text: str) -> list[AgendaItem]:
        """
        Parse individual agenda items from the raw text of an agenda PDF.
        Uses simple section-based parsing.
        """
        items = []
        if not text:
            return items

        # Common agenda section headers
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

            # Check if this line is a section header
            for pattern in section_patterns:
                if re.search(pattern, line, re.IGNORECASE):
                    current_section = line
                    break
            else:
                # This is an agenda item
                if len(line) > 10:  # Skip short lines
                    items.append(AgendaItem(
                        title=line[:200],  # Truncate long titles
                        description=line if len(line) > 200 else None,
                        category=current_section,
                    ))

        return items

    async def get_latest_agenda(self) -> Optional[Agenda]:
        """Fetch the most recent city council agenda."""
        agendas = await self.fetch_agenda_list()
        if not agendas:
            return None

        latest = agendas[0]

        # Try to get PDF text
        raw_text = None
        if latest.get("pdf_url"):
            raw_text = await self.fetch_agenda_pdf_text(latest["pdf_url"])

        # Parse items from text
        items = self._parse_agenda_items_from_text(raw_text) if raw_text else []

        return Agenda(
            id=latest["id"],
            city=self.city,
            state=self.state,
            meeting_date=latest["meeting_date"] or datetime.utcnow(),
            meeting_type="City Council Regular Meeting",
            title=latest["title"],
            url=latest["url"] or "",
            pdf_url=latest.get("pdf_url"),
            items=items,
            raw_text=raw_text,
            source="civicplus",
        )

    async def list_agendas(self, limit: int = 10) -> list[dict]:
        """List recent agendas with metadata (no full parsing)."""
        agendas = await self.fetch_agenda_list()
        return [
            {
                "id": a["id"],
                "title": a["title"],
                "meeting_date": a["meeting_date"].isoformat() if a["meeting_date"] else None,
                "url": a["url"],
                "pdf_url": a["pdf_url"],
            }
            for a in agendas[:limit]
        ]
