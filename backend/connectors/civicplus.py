"""
CivicPlus connector for Civic City Hub.

NOTE: This connector is currently unused. The app uses the Laserfiche connector
directly for Paris, TX. This file is kept for future use when adding cities
that use CivicPlus for their agenda management.

Scrapes city council agendas from CivicPlus-powered municipal websites.
"""

import re
import uuid
from datetime import datetime
from typing import Optional

import httpx
from bs4 import BeautifulSoup

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
