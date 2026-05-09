"""
Laserfiche WebLink connector for Civic City Hub.

Paris, TX stores city council minutes in Laserfiche WebLink at
https://documents.paristexas.gov/weblink/. The system provides RSS feeds
for folder contents, which we use to discover minutes documents.

Minutes folder structure (2 levels deep):
  Minutes (20)
    -> 2026 (1396340), 2025 (1365526), 2024 (1341834), ...
      -> 01-12-2026 (docid), 01-28-2026 (docid), ...  (minutes documents)

RSS feed URL pattern:
  https://documents.paristexas.gov/WebLink/rss/dbid/0/folder/{folderId}/feed.rss

Document viewer URL pattern:
  https://documents.paristexas.gov/WebLink/docview.aspx?id={docId}&dbid=0

Page image URL pattern:
  https://documents.paristexas.gov/WebLink/0/doc/{docId}/Page{pageNum}.aspx

NOTE: Laserfiche stores documents as scanned images (TIFF), not text PDFs.
The docview.aspx returns an HTML viewer page with page image URLs embedded
in the toolbar. We download these page images and use Tesseract OCR (free,
open-source) to extract text from the scanned images, then pass the text
to DeepSeek for summarization.
"""

import hashlib
import json
import re
from datetime import datetime, timezone
from typing import Optional
from xml.etree import ElementTree as ET

import httpx
from bs4 import BeautifulSoup

from models.schemas import Minutes

# Laserfiche folder IDs for Paris, TX
LASERFICHE_BASE = "https://documents.paristexas.gov/WebLink"
MINUTES_FOLDER_ID = "20"
DBID = "0"


class LaserficheConnector:
    """Connector for Laserfiche WebLink document management systems.

    Discovers city council minutes via RSS feeds and provides
    viewer URLs for the scanned document pages.

    The folder structure is 2 levels deep:
      Minutes (20) -> Year (2026) -> Document (01-12-2026)
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

        now = datetime.now(timezone.utc)
        minutes_list = []
        for doc in documents:
            # Parse meeting date from the document title (e.g. "01-12-2026")
            meeting_date = self._parse_date_from_minutes_title(doc["title"])

            # Fall back to pubDate
            if not meeting_date and doc["pub_date"]:
                meeting_date = doc["pub_date"]

            # Skip documents with future meeting dates — these are likely
            # agenda packets uploaded in advance, not actual minutes.
            # For example, "05-20-2026" uploaded on Apr 14 is an agenda
            # for a future meeting, not minutes of a past meeting.
            if meeting_date and meeting_date > now:
                print(
                    f"[SKIP] '{doc['title']}' has future meeting date "
                    f"{meeting_date.strftime('%Y-%m-%d')}, skipping "
                    f"(likely agenda packet, not minutes)"
                )
                continue

            document_url = (
                self._document_viewer_url(doc["entity_id"])
                if doc["entity_id"]
                else None
            )

            # Build a descriptive title
            title = doc["title"]
            display_title = f"City Council Meeting Minutes - {title}"

            # Generate a deterministic ID from the document URL so the same
            # document always gets the same ID across API calls.
            doc_id_str = document_url or doc.get("entity_id", "") or doc.get("title", "")
            stable_id = hashlib.md5(doc_id_str.encode()).hexdigest()[:8]

            minutes_list.append({
                "id": stable_id,
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

    async def fetch_document_text(self, document_url: str) -> Optional[str]:
        """Attempt to extract text from a Laserfiche document.

        NOTE: Laserfiche stores documents as scanned images (TIFF).
        The docview.aspx returns an HTML viewer page with page image
        URLs embedded in the toolbar navigation.

        This method extracts the page image URLs from the viewer HTML
        and returns them as a structured text block that the LLM
        summarizer can use with GPT-4o Vision to read the scanned images.

        Returns a structured text block with page image URLs.
        """
        if not document_url:
            return None

        try:
            response = await self.client.get(document_url)
            response.raise_for_status()

            html = response.text

            # Extract page image URLs from the toolbar navigation links
            # Pattern: /WebLink/0/doc/{docId}/Page{pageNum}.aspx
            page_urls = self._extract_page_image_urls(html, document_url)

            if page_urls:
                lines = [
                    "[This document is a scanned image. "
                    "Page images are available at the following URLs:]"
                ]
                for i, url in enumerate(page_urls, 1):
                    lines.append(f"[Page {i}: {url}]")
                return "\n".join(lines)

            # Fallback: return the viewer URL
            return (
                f"[This document is a scanned image available at: "
                f"{document_url}]"
            )
        except Exception as e:
            print(f"[WARN] Error accessing document viewer: {e}")
            return None

    async def fetch_page_image_urls(
        self, document_url: str
    ) -> list[str]:
        """Fetch and extract page image URLs from a document viewer page.

        Returns a list of full URLs to each page image, which can be
        used for OCR text extraction.
        """
        if not document_url:
            return []

        try:
            response = await self.client.get(document_url)
            response.raise_for_status()
            return self._extract_page_image_urls(
                response.text, document_url
            )
        except Exception as e:
            print(
                f"[WARN] Error fetching page image URLs: {e}"
            )
            return []

    async def fetch_page_images(
        self, document_url: str
    ) -> list[bytes]:
        """Download actual page images from Laserfiche via PDF generation.

        Strategy (more reliable than direct page image download):
        1. Visit docview.aspx to establish session cookies
        2. POST to GeneratePDF.aspx to generate a PDF of the document
        3. Use PyMuPDF (fitz) to render each PDF page to a PIL Image
        4. Return the image bytes for Tesseract OCR

        This avoids the CookieCheck.aspx redirect issue that plagues
        direct Page.aspx image downloads.
        """
        if not document_url:
            return []

        # Extract docId from the URL
        doc_id = None
        match = re.search(r"id=(\d+)", document_url)
        if match:
            doc_id = match.group(1)

        if not doc_id:
            print("[WARN] Could not extract docId from document URL")
            return []

        # Step 1: Visit docview.aspx to establish session cookies
        try:
            await self.client.get(document_url)
        except Exception as e:
            print(f"[WARN] Error accessing document viewer: {e}")
            # Continue anyway — cookies might not be needed for GeneratePDF

        # Step 2: POST to GeneratePDF.aspx to get a PDF
        gen_url = f"{self.base_url}/GeneratePDF.aspx"
        try:
            pdf_response = await self.client.post(
                gen_url,
                data={
                    "id": doc_id,
                    "dbid": DBID,
                    "pageFrom": "1",
                    "pageTo": "999",  # Request all pages
                },
                headers={
                    "Content-Type": "application/x-www-form-urlencoded",
                },
                timeout=60.0,  # PDF generation can be slow
            )
            pdf_response.raise_for_status()

            content_type = pdf_response.headers.get("content-type", "")
            pdf_bytes = pdf_response.content

            if not pdf_bytes or len(pdf_bytes) < 100:
                print(f"[WARN] GeneratePDF returned empty or too small response ({len(pdf_bytes)} bytes)")
                return []

            # Check if we got HTML (error page) instead of PDF
            if b"<html" in pdf_bytes[:100].lower() or b"<!DOCTYPE" in pdf_bytes[:100]:
                print(f"[WARN] GeneratePDF returned HTML instead of PDF (likely an error page)")
                print(f"[WARN] Response preview: {pdf_bytes[:300]}")
                return []

            print(f"[PDF] Generated PDF: {len(pdf_bytes)} bytes, Content-Type: {content_type}")

        except Exception as e:
            print(f"[WARN] GeneratePDF POST failed: {e}")
            return []

        # Step 3: Render PDF pages to images using PyMuPDF
        images: list[bytes] = []
        try:
            import fitz  # PyMuPDF

            pdf_doc = fitz.open(stream=pdf_bytes, filetype="pdf")
            num_pages = len(pdf_doc)
            print(f"[PDF] Rendering {num_pages} pages from PDF")

            for page_num in range(num_pages):
                try:
                    page = pdf_doc[page_num]
                    # Render at 300 DPI for good OCR quality
                    zoom = 300 / 72  # 72 is default PDF DPI
                    mat = fitz.Matrix(zoom, zoom)
                    pix = page.get_pixmap(matrix=mat)
                    img_bytes = pix.tobytes("png")
                    images.append(img_bytes)
                    print(f"[PDF] Rendered page {page_num + 1}: {len(img_bytes)} bytes")
                except Exception as e:
                    print(f"[WARN] Failed to render page {page_num + 1}: {e}")

            pdf_doc.close()

        except ImportError:
            print("[WARN] PyMuPDF (fitz) not installed. Cannot render PDF pages.")
            print("       Install with: pip install PyMuPDF")
            return []
        except Exception as e:
            print(f"[WARN] Failed to render PDF pages: {e}")
            return []

        return images

    def _extract_page_image_urls(
        self, html: str, viewer_url: str
    ) -> list[str]:
        """Extract page image URLs from the docview.aspx HTML.

        Laserfiche DocViewer8 serves each page as a separate image at:
          /WebLink/0/doc/{docId}/Page{pageNum}.aspx

        These URLs appear in the page toolbar navigation links.
        We also extract the docId from the page toolbar or docInfo JSON.
        """
        page_urls = []

        # Method 1: Extract from page toolbar links
        # Pattern: href="/WebLink/0/doc/{docId}/Page{pageNum}.aspx"
        soup = BeautifulSoup(html, "html.parser")
        for link in soup.find_all("a", href=True):
            href = link["href"]
            match = re.search(
                r"/WebLink/0/doc/(\d+)/Page(\d+)\.aspx", href
            )
            if match:
                doc_id = match.group(1)
                page_num = int(match.group(2))
                full_url = (
                    f"{LASERFICHE_BASE}/0/doc/{doc_id}/Page{page_num}.aspx"
                )
                if full_url not in page_urls:
                    page_urls.append(full_url)

        # Method 2: Extract from docInfo JSON in JavaScript
        if not page_urls:
            doc_id = self._extract_doc_id_from_html(html, viewer_url)
            num_pages = self._extract_num_pages_from_html(html)
            if doc_id and num_pages:
                for page_num in range(1, num_pages + 1):
                    page_urls.append(
                        f"{LASERFICHE_BASE}/0/doc/{doc_id}/Page{page_num}.aspx"
                    )

        # Sort by page number
        page_urls.sort(
            key=lambda u: int(re.search(r"Page(\d+)\.aspx", u).group(1))
            if re.search(r"Page(\d+)\.aspx", u)
            else 0
        )

        return page_urls

    def _extract_doc_id_from_html(
        self, html: str, viewer_url: str
    ) -> Optional[str]:
        """Extract document ID from docInfo JSON or form action."""
        # Try docInfo JSON
        match = re.search(
            r'"Id"\s*:\s*(\d+)', html
        )
        if match:
            return match.group(1)

        # Try form action
        match = re.search(
            r'action="[^"]*DocView\.aspx\?id=(\d+)', html
        )
        if match:
            return match.group(1)

        # Try extracting from the viewer URL itself
        match = re.search(r"id=(\d+)", viewer_url)
        if match:
            return match.group(1)

        return None

    def _extract_num_pages_from_html(self, html: str) -> Optional[int]:
        """Extract number of pages from docInfo JSON."""
        match = re.search(r'"NumPages"\s*:\s*(\d+)', html)
        if match:
            return int(match.group(1))
        return None

    async def get_latest_minutes(self) -> Optional[Minutes]:
        """Fetch the most recent city council minutes from Laserfiche."""
        minutes_list = await self.fetch_minutes_list(limit=5)
        if not minutes_list:
            return None

        latest = minutes_list[0]

        # Access the document viewer (returns HTML, not PDF text)
        raw_text = None
        page_image_urls: list[str] = []
        if latest.get("document_url"):
            raw_text = await self.fetch_document_text(
                latest["document_url"]
            )
            page_image_urls = await self.fetch_page_image_urls(
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
            page_image_urls=page_image_urls,
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
