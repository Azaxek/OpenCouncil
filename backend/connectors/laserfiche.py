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
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/120.0.0.0 Safari/537.36"
                ),
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "en-US,en;q=0.5",
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
        self, document_url: str, page_urls: Optional[list[str]] = None
    ) -> list[bytes]:
        """Download actual page images from Laserfiche.

        Primary strategy (PDF generation):
        1. Visit docview.aspx to establish session cookies
        2. Extract ASP.NET __VIEWSTATE and __EVENTVALIDATION tokens from the HTML
        3. POST to GeneratePDF.aspx with ViewState tokens to generate a PDF
        4. Use PyMuPDF (fitz) to render each PDF page to a PIL Image

        Fallback strategy (direct page download):
        If PDF generation fails (e.g. on HF Spaces where the Laserfiche
        server may block the request), try downloading each page URL
        directly and extracting the embedded image.

        Returns image bytes for OCR processing.
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
        # and extract ASP.NET ViewState tokens needed for GeneratePDF POST
        viewstate = None
        eventvalidation = None
        docview_html = None
        try:
            docview_response = await self.client.get(
                document_url,
                headers={
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                    "Accept-Language": "en-US,en;q=0.5",
                },
                timeout=30.0,
            )
            docview_response.raise_for_status()
            docview_html = docview_response.text

            # Extract __VIEWSTATE from the docview.aspx HTML
            vs_match = re.search(
                r'<input[^>]*name="__VIEWSTATE"[^>]*value="([^"]*)"',
                docview_html,
            )
            if vs_match:
                viewstate = vs_match.group(1)
                print(f"[PDF] Extracted __VIEWSTATE ({len(viewstate)} chars)")

            # Extract __EVENTVALIDATION from the docview.aspx HTML
            ev_match = re.search(
                r'<input[^>]*name="__EVENTVALIDATION"[^>]*value="([^"]*)"',
                docview_html,
            )
            if ev_match:
                eventvalidation = ev_match.group(1)
                print(f"[PDF] Extracted __EVENTVALIDATION ({len(eventvalidation)} chars)")

        except Exception as e:
            print(f"[WARN] Error accessing document viewer: {e}")
            # Continue anyway — cookies might not be needed for GeneratePDF

        # Step 2: POST to GeneratePDF.aspx to get a PDF
        gen_url = f"{self.base_url}/GeneratePDF.aspx"
        pdf_bytes = None
        try:
            # Build POST data with ViewState tokens if available
            post_data: dict[str, str] = {
                "id": doc_id,
                "dbid": DBID,
                "pageFrom": "1",
                "pageTo": "999",  # Request all pages
            }
            if viewstate:
                post_data["__VIEWSTATE"] = viewstate
            if eventvalidation:
                post_data["__EVENTVALIDATION"] = eventvalidation

            pdf_response = await self.client.post(
                gen_url,
                data=post_data,
                headers={
                    "Content-Type": "application/x-www-form-urlencoded",
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                    "Accept-Language": "en-US,en;q=0.5",
                    "Referer": document_url,
                },
                timeout=60.0,  # PDF generation can be slow
            )
            pdf_response.raise_for_status()

            content_type = pdf_response.headers.get("content-type", "")
            pdf_bytes = pdf_response.content

            if not pdf_bytes or len(pdf_bytes) < 100:
                print(f"[WARN] GeneratePDF returned empty or too small response ({len(pdf_bytes)} bytes)")
                pdf_bytes = None
            elif self._is_error_response(pdf_bytes):
                print(f"[WARN] GeneratePDF returned error page instead of PDF ({len(pdf_bytes)} bytes, Content-Type: {content_type})")
                pdf_bytes = None
            else:
                print(f"[PDF] Generated PDF: {len(pdf_bytes)} bytes, Content-Type: {content_type}")

        except Exception as e:
            print(f"[WARN] GeneratePDF POST failed: {e}")
            pdf_bytes = None

        # Step 3: If we got a valid PDF, render it to images
        if pdf_bytes:
            images = self._render_pdf_to_images(pdf_bytes)
            if images:
                return images
            print("[WARN] PDF rendering returned no images, trying fallback...")

        # Step 4: Fallback — download individual page images directly
        # This handles cases where GeneratePDF.aspx is blocked (e.g. HF Spaces)
        print("[FALLBACK] Trying direct page image download...")
        return await self._fetch_page_images_fallback(doc_id, page_urls, docview_html)

    def _is_error_response(self, content: bytes) -> bool:
        """Check if the response content is an error page rather than a valid PDF.

        Detects:
        - HTML pages (<html, <!DOCTYPE)
        - ASP.NET error pages (JavaScript alerts, "Object reference" errors)
        - XML error responses
        """
        if not content:
            return True

        head = content[:500].lower()

        # Check for HTML tags
        if b"<html" in head or b"<!DOCTYPE" in head:
            return True

        # Check for ASP.NET error patterns
        error_patterns = [
            b"object reference not set",
            b"nullreferenceexception",
            b"exception of type",
            b"error has occurred",
            b"could not complete your request",
            b"the system has encountered an error",
            b"alert(",
            b"stack trace:",
        ]
        for pattern in error_patterns:
            if pattern in head:
                return True

        # Check for XML with error indicators
        if b"<?xml" in head:
            # XML responses from GeneratePDF are usually errors
            # A valid PDF starts with %PDF
            if b"<html" in content[:2000].lower() or b"error" in content[:2000].lower():
                return True

        # Check if it starts with PDF magic bytes
        if content[:4] == b"%PDF":
            return False

        # If it doesn't start with PDF magic bytes and isn't clearly an error,
        # it's likely not a valid PDF
        if len(content) < 1000:
            return True

        return False

    def _render_pdf_to_images(self, pdf_bytes: bytes) -> list[bytes]:
        """Render PDF pages to PNG images using PyMuPDF."""
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
        except Exception as e:
            print(f"[WARN] Failed to render PDF pages: {e}")

        return images

    async def _fetch_page_images_fallback(
        self, doc_id: str, page_urls: Optional[list[str]] = None, docview_html: Optional[str] = None
    ) -> list[bytes]:
        """Fallback: download individual page images directly from Laserfiche.

        Tries multiple strategies:
        1. Download each page URL directly (Page1.aspx, Page2.aspx, etc.)
           and extract docInfo JSON with PageIds from the HTML.
        2. Try the GetImage.aspx endpoint with PageIds from docInfo JSON.
        3. Try GetImage.aspx with sequential page ID enumeration.

        Returns a list of PNG image bytes.
        """
        images: list[bytes] = []

        # Strategy 1: Try downloading each page URL and extracting docInfo
        if page_urls:
            for i, page_url in enumerate(page_urls):
                try:
                    print(f"[FALLBACK] Downloading page {i + 1}: {page_url}")
                    response = await self.client.get(
                        page_url,
                        headers={
                            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                            "Accept-Language": "en-US,en;q=0.5",
                        },
                        timeout=30.0,
                    )
                    response.raise_for_status()

                    content = response.content
                    content_type = response.headers.get("content-type", "")

                    # Check if we got an image directly
                    if content_type.startswith("image/"):
                        img_bytes = self._convert_to_png_bytes(content)
                        if img_bytes:
                            images.append(img_bytes)
                            print(f"[FALLBACK] Page {i + 1}: Got image ({len(img_bytes)} bytes, {content_type})")
                            continue

                    # If we got HTML, try to extract the image from docInfo JSON
                    html = response.text
                    img_bytes = await self._extract_image_from_page_html(html, doc_id, i + 1)
                    if img_bytes:
                        images.append(img_bytes)
                        print(f"[FALLBACK] Page {i + 1}: Extracted image from HTML ({len(img_bytes)} bytes)")
                        continue

                    print(f"[FALLBACK] Page {i + 1}: Could not extract image from response")

                except Exception as e:
                    print(f"[FALLBACK] Page {i + 1}: Download failed: {e}")
                    continue

        if images:
            return images

        # Strategy 2: Try GetImage.aspx with page IDs from docInfo
        # Pass the already-fetched docview_html to avoid a redundant HTTP request
        print("[FALLBACK] Trying GetImage.aspx endpoint...")
        return await self._fetch_via_getimage(doc_id, docview_html)

    async def _extract_image_from_page_html(
        self, html: str, doc_id: str, page_num: int
    ) -> Optional[bytes]:
        """Extract a page image from the Laserfiche page HTML.

        The page HTML contains a docInfo JSON with PageIds that can be
        used to construct GetImage.aspx URLs. Also tries to extract
        ViewState tokens for authenticated requests.
        """
        # Extract __VIEWSTATE from the page HTML for authenticated requests
        viewstate = None
        vs_match = re.search(
            r'<input[^>]*name="__VIEWSTATE"[^>]*value="([^"]*)"',
            html,
        )
        if vs_match:
            viewstate = vs_match.group(1)

        # Extract __EVENTVALIDATION
        eventvalidation = None
        ev_match = re.search(
            r'<input[^>]*name="__EVENTVALIDATION"[^>]*value="([^"]*)"',
            html,
        )
        if ev_match:
            eventvalidation = ev_match.group(1)

        # Try to extract docInfo JSON from the HTML
        doc_info_match = re.search(
            r'var\s+docInfo\s*=\s*(\{.*?"PageIds"\s*:\s*\[.*?\]\s*.*?\});',
            html,
            re.DOTALL,
        )
        if doc_info_match:
            try:
                doc_info = json.loads(doc_info_match.group(1))
                page_ids = doc_info.get("PageIds", [])
                dbid = doc_info.get("DBID", DBID)
                doc_id_from_info = str(doc_info.get("Id", doc_id))

                # PageIds[0] is a placeholder (0), actual pages start at index 1
                if len(page_ids) > page_num:
                    page_id = page_ids[page_num]
                    if page_id and page_id > 0:
                        # Try GetImage.aspx with the page ID
                        img_url = (
                            f"{self.base_url}/GetImage.aspx"
                            f"?pageid={page_id}&dbid={dbid}&docid={doc_id_from_info}"
                        )
                        print(f"[FALLBACK] Trying GetImage.aspx: {img_url}")
                        try:
                            img_response = await self.client.get(
                                img_url,
                                headers={
                                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                                    "Accept": "image/avif,image/webp,image/apng,image/*,*/*;q=0.8",
                                    "Accept-Language": "en-US,en;q=0.5",
                                    "Referer": f"{self.base_url}/docview.aspx?id={doc_id_from_info}&dbid={dbid}",
                                },
                                timeout=30.0,
                            )
                            img_response.raise_for_status()
                            img_content = img_response.content
                            content_type = img_response.headers.get("content-type", "")
                            if content_type.startswith("image/") and len(img_content) > 1000:
                                return self._convert_to_png_bytes(img_content)
                            elif len(img_content) > 1000 and not self._is_error_response(img_content):
                                # Might be an image with wrong content-type
                                return self._convert_to_png_bytes(img_content)
                        except Exception as e:
                            print(f"[FALLBACK] GetImage.aspx failed: {e}")

                        # Also try with format parameter
                        for fmt in ["png", "tiff", "jpeg"]:
                            try:
                                img_url_fmt = (
                                    f"{self.base_url}/GetImage.aspx"
                                    f"?pageid={page_id}&dbid={dbid}&docid={doc_id_from_info}"
                                    f"&format={fmt}"
                                )
                                img_response = await self.client.get(
                                    img_url_fmt,
                                    headers={
                                        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                                        "Accept": "image/avif,image/webp,image/apng,image/*,*/*;q=0.8",
                                        "Referer": f"{self.base_url}/docview.aspx?id={doc_id_from_info}&dbid={dbid}",
                                    },
                                    timeout=30.0,
                                )
                                img_response.raise_for_status()
                                img_content = img_response.content
                                if len(img_content) > 1000 and not self._is_error_response(img_content):
                                    return self._convert_to_png_bytes(img_content)
                            except Exception:
                                continue
            except (json.JSONDecodeError, KeyError, IndexError) as e:
                print(f"[FALLBACK] Failed to parse docInfo JSON: {e}")

        return None

    async def _fetch_via_getimage(self, doc_id: str, existing_html: Optional[str] = None) -> list[bytes]:
        """Last resort: try to get page images via GetImage.aspx.

        Uses the docInfo JSON from the docview.aspx page to get PageIds,
        then tries GetImage.aspx with each page ID.

        Args:
            doc_id: The Laserfiche document ID.
            existing_html: Previously fetched docview.aspx HTML to avoid redundant requests.
        """
        images: list[bytes] = []

        # Use existing HTML if provided (avoids redundant HTTP request)
        html = existing_html
        docview_url = f"{self.base_url}/docview.aspx?id={doc_id}&dbid={DBID}"

        # Fetch docview.aspx if we don't already have the HTML
        if not html:
            try:
                response = await self.client.get(
                    docview_url,
                    headers={
                        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                    },
                    timeout=30.0,
                )
                response.raise_for_status()
                html = response.text
            except Exception as e:
                print(f"[FALLBACK] Failed to get docInfo from docview.aspx: {e}")
                return images

        # Extract docInfo JSON
        try:
            doc_info_match = re.search(
                r'var\s+docInfo\s*=\s*(\{.*?"PageIds"\s*:\s*\[.*?\]\s*.*?\});',
                html,
                re.DOTALL,
            )
            if doc_info_match:
                doc_info = json.loads(doc_info_match.group(1))
                page_ids = doc_info.get("PageIds", [])
                dbid = doc_info.get("DBID", DBID)
                doc_id_from_info = str(doc_info.get("Id", doc_id))

                print(f"[FALLBACK] Got docInfo: {len(page_ids) - 1} pages, PageIds={page_ids}")

                # Try each page ID with GetImage.aspx
                for page_num in range(1, len(page_ids)):
                    page_id = page_ids[page_num]
                    if page_id and page_id > 0:
                        img_url = (
                            f"{self.base_url}/GetImage.aspx"
                            f"?pageid={page_id}&dbid={dbid}&docid={doc_id_from_info}"
                        )
                        try:
                            img_response = await self.client.get(
                                img_url,
                                headers={
                                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                                    "Accept": "image/avif,image/webp,image/apng,image/*,*/*;q=0.8",
                                    "Referer": docview_url,
                                },
                                timeout=30.0,
                            )
                            img_response.raise_for_status()
                            img_content = img_response.content
                            content_type = img_response.headers.get("content-type", "")

                            if content_type.startswith("image/") and len(img_content) > 1000:
                                img_bytes = self._convert_to_png_bytes(img_content)
                                if img_bytes:
                                    images.append(img_bytes)
                                    print(f"[FALLBACK] GetImage.aspx page {page_num}: Got image ({len(img_bytes)} bytes)")
                                    continue

                            # Check if it's an error page
                            if self._is_error_response(img_content):
                                print(f"[FALLBACK] GetImage.aspx page {page_num}: Got error page ({len(img_content)} bytes, {content_type})")
                            else:
                                # Try to convert anyway
                                img_bytes = self._convert_to_png_bytes(img_content)
                                if img_bytes:
                                    images.append(img_bytes)
                                    print(f"[FALLBACK] GetImage.aspx page {page_num}: Got image ({len(img_bytes)} bytes)")

                        except Exception as e:
                            print(f"[FALLBACK] GetImage.aspx page {page_num}: Failed: {e}")

        except (json.JSONDecodeError, KeyError, IndexError) as e:
            print(f"[FALLBACK] Failed to parse docInfo JSON: {e}")

        if images:
            return images

        print("[FALLBACK] All GetImage.aspx attempts failed")
        return images

    def _convert_to_png_bytes(self, image_data: bytes) -> Optional[bytes]:
        """Convert image data to PNG bytes using PIL."""
        try:
            from PIL import Image
            import io

            img = Image.open(io.BytesIO(image_data))
            # Convert to RGB if necessary (e.g. RGBA, CMYK, P mode)
            if img.mode not in ("RGB", "L"):
                img = img.convert("RGB")
            buf = io.BytesIO()
            img.save(buf, format="PNG")
            return buf.getvalue()
        except Exception as e:
            print(f"[FALLBACK] Image conversion failed: {e}")
            return None

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
        doc_id = None
        num_pages = None

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

        # Method 2: Extract total page count from toolbar display
        # Pattern: <span class="PageNumberToolbarCount">4</span>
        if not num_pages:
            count_match = re.search(
                r'class="PageNumberToolbarCount"[^>]*>(\d+)</span>',
                html
            )
            if count_match:
                num_pages = int(count_match.group(1))

        # Method 3: Extract from docInfo JSON in JavaScript
        if not doc_id:
            doc_id = self._extract_doc_id_from_html(html, viewer_url)
        if not num_pages:
            num_pages = self._extract_num_pages_from_html(html)

        # Method 4: Extract doc_id from the viewer URL itself
        if not doc_id:
            match = re.search(r"id=(\d+)", viewer_url)
            if match:
                doc_id = match.group(1)

        # If we have doc_id and num_pages, generate all page URLs
        if doc_id and num_pages and len(page_urls) < num_pages:
            existing_pages = set()
            for url in page_urls:
                m = re.search(r"Page(\d+)\.aspx", url)
                if m:
                    existing_pages.add(int(m.group(1)))
            for page_num in range(1, num_pages + 1):
                if page_num not in existing_pages:
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
            # Extract page image URLs from the raw_text that was already fetched
            # (avoids a second HTTP request that might get different HTML)
            if raw_text:
                for line in raw_text.split("\n"):
                    match = re.search(r'\[Page \d+: (.+)\]', line)
                    if match:
                        page_image_urls.append(match.group(1))
            # Fall back to direct fetch if raw_text had no URLs
            if not page_image_urls:
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
