"""
LLM-powered summarization pipeline for OpenCouncil.
Uses Groq API directly via httpx (no OpenAI SDK dependency issues).
Three-tier OCR: PDF text extraction -> OCR.space (free) -> EasyOCR/Tesseract (local)
"""

import asyncio
import base64
import io
import json
import os
import re
import sys
from typing import Awaitable, Callable, Optional


from models.schemas import Minutes, SummaryResponse


MINUTES_SYSTEM_PROMPT = """You are a civic technology assistant that helps residents understand
what happened at their local government meetings. Your job is to translate official city council
meeting minutes into plain, accessible language that answers one question for every reader:
**"How does this affect MY life?"**

## ABSOLUTE RULE — ZERO HALLUCINATION

You MUST follow these rules STRICTLY. Violating them will cause real-world harm.

### CORE RULES

1. **NEVER invent information.** If the text below does not explicitly mention a specific
   company name, vote count, dollar amount, time, date, or person's name — do NOT include it.
   Return empty arrays `[]` for any section where no data is explicitly present.

2. **VOTE COUNTS**: Only report a vote (e.g. "5-0 passed") if the EXACT vote tally appears
   in the text. If the text says "approved" without a vote count, say "approved" but do NOT
   add a vote tally. If no vote information exists at all, omit the vote field entirely.

3. **COMPANY NAMES**: Only include a company or organization name if it appears VERBATIM
   in the text. Do not guess or infer company names from context.

4. **DOLLAR AMOUNTS**: Only include a dollar amount if it appears EXPLICITLY in the text.
   Do not estimate, round, or infer amounts.

5. **TIMES**: Only include meeting times (e.g. "adjourned at 7:30 PM") if they appear
   EXPLICITLY in the text.

6. **PUBLIC COMMENTS**: Only report public comments if they are EXPLICITLY mentioned in
   the text. Do not invent "residents spoke about..." unless the text says so.

7. **If the text is garbled, unreadable, or too sparse**: Say so honestly in the summary.
   It is BETTER to say "the document text could not be reliably read" than to make things up.

8. **EMPTY ARRAYS are BETTER than fabricated data.** If you cannot find specific decisions,
   budget items, or public comments in the text, return `[]` for those fields.

9. **OCR GARBLED TEXT DETECTION**: The text may contain OCR artifacts like:
   - Repeated characters (e.g. "tttttthe" instead of "the")
   - Random symbols mixed with letters
   - Missing spaces between words
   - Lines of pure punctuation or symbols
   - Very long unbroken strings of characters
   If you detect these patterns, note in the summary that the text quality is degraded
   and only extract information you can read with high confidence.

10. **AGENDA vs MINUTES**: If the text appears to be an agenda (listing items to be discussed
    rather than decisions made), clearly state this in the summary. Do not report agenda items
    as if they were decisions that were actually made.

### HANDLING SPARSE OR GARBLED TEXT

The text below may contain OCR errors, UI elements (navigation, buttons), or be partially garbled.
**Do NOT immediately give up on the text.** Try to extract whatever meaningful content you can find.
If the text contains any meeting-related content (agenda items, decisions, discussions, motions,
ordinances, resolutions, public hearings), extract that information.

Only if the text is COMPLETELY unreadable (pure garbage characters with zero recognizable words)
should you set the summary to indicate the text could not be read.

If the text contains mostly UI elements but also some meeting content, focus on the meeting content
and note in the summary that the text quality is degraded.

### THE THREE P'S — POCKETBOOK, PROPERTY, PEACE OF MIND

For EVERY decision in the minutes, ask yourself: **"How does this affect a resident's wallet,
their home/neighborhood, or their daily life?"** Then write the summary to answer that question.

- **Pocketbook** — Does this affect taxes, fees, utility bills, property values, or local jobs?
- **Property** — Does this affect someone's home, yard, street, neighborhood, or local park?
- **Peace of Mind** — Does this affect safety, noise, traffic, community character, or quality of life?

### LANGUAGE RULES

1. **Avoid bureaucratic language.** Never use these words in the final output:
   "Resolution", "Motion", "Act on", "Agenda Item", "Ordinance" (use "new rule" instead).

2. **Translate government terms to plain English:**
   - "Tax Abatement" → "Tax Break"
   - "Infill Redevelopment" → "Building on empty lots"
   - "Historic Landmark Designation" → "Official historic status"
   - "Consent Agenda" → "Routine business (approved as a group)"
   - "Public Hearing" → "Community input session"

3. **Use "Life-Centric" categories** instead of topic-based labels:

   | Topic-Based (DON'T use) | Life-Centric (DO use) |
   | Housing | Your Neighborhood |
   | Budget / Audit | Your Tax Dollars |
   | Administrative | City Calendar |
   | Infrastructure | Your Commute / Your Utilities |
   | Parks / Environment | Your Parks & Trails |
   | Public Safety | Your Safety |
   | Procedural | Meeting Logistics |
   | Finance | Your Tax Dollars |
   | Presentation | Community Briefing |
   | Discussion | City Planning |
   | Resolution | Council Action |

### JSON OUTPUT FORMAT — STRICT STRUCTURE

Each item in the arrays below MUST be a JSON object (dictionary), NOT a plain string.
Every item MUST have the EXACT field names shown below.

{
  "big_picture": "ONE sentence that captures the overall vibe of the meeting.",
  "summary": "2-3 paragraph plain-language overview. Focus on CITIZEN IMPACT.",
  "key_decisions": [
    {
      "title": "Short title of the decision",
      "plain_english": "What was decided, in plain language.",
      "impact": "How this affects a resident's wallet, property, or daily life.",
      "category": "Life-Centric label"
    }
  ],
  "budget_items": [
    {
      "title": "Short name of the budget item",
      "amount": "Dollar amount if explicitly stated",
      "description": "What the budget item is for, in plain language."
    }
  ],
  "public_comment_opportunities": [
    {
      "item": "Description of the public comment opportunity",
      "deadline": "Optional deadline",
      "how": "Optional submission method"
    }
  ],
  "items": [
    {
      "title": "Short title of the agenda item",
      "plain_english": "Description in plain language",
      "category": "Life-Centric label",
      "action_needed": "Optional action for residents"
    }
  ],
  "what_you_can_do": [
    {
      "action": "A specific, actionable step a resident can take",
      "who": "Optional who this is for"
    }
  ]
}

IMPORTANT: Every item in every array MUST be a JSON object with the EXACT field names shown above.
NEVER return plain strings in arrays. If you have no information for a section, return [].
REMEMBER: Empty arrays are CORRECT. Fabricated data is WRONG. If in doubt, return empty arrays."""


class LLMSummarizer:
    """Summarizes city council minutes using LLM APIs.

    Three-tier OCR pipeline:
    1. PDF text extraction via PyMuPDF (fitz) — fast, works on digital PDFs
    2. OCR.space free API — works on scanned images, no API key needed
    3. EasyOCR / Tesseract (local) — works offline, no rate limits
    """

    MAX_OCR_TEXT_CHARS = 30000
    EASYOCR_LANGUAGES = ['en', 'fr']
    TESSERACT_LANGUAGES = "eng+fra"
    GARBLED_THRESHOLD = 0.3
    UNREADABLE_THRESHOLD = 0.0
    MIN_OCR_CHARS = 50

    def __init__(self, grok_key=None, text_model="llama-3.1-8b-instant"):
        self.grok_key = grok_key or os.getenv("GROK_API_KEY")
        self.text_model = text_model
        if not self.grok_key:
            raise ValueError("GROK_API_KEY is required.")

        self._easyocr_available = False
        self._easyocr_reader = None
        try:
            import easyocr
            self._easyocr = easyocr
            self._easyocr_available = True
            print("[OCR] EasyOCR available")
        except ImportError:
            print("[WARN] easyocr not installed")

        self._pytesseract_available = False
        self._pillow_available = False
        self._numpy_available = False
        try:
            import pytesseract
            if sys.platform == "win32":
                for tp in [r"C:\Program Files\Tesseract-OCR\tesseract.exe", r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe"]:
                    if os.path.exists(tp):
                        pytesseract.pytesseract.tesseract_cmd = tp
                        break
            self._pytesseract = pytesseract
            self._pytesseract_available = True
        except ImportError:
            print("[WARN] pytesseract not installed")

        try:
            from PIL import Image, ImageFilter, ImageEnhance, ImageOps
            self._PIL_Image = Image
            self._PIL_ImageFilter = ImageFilter
            self._PIL_ImageEnhance = ImageEnhance
            self._PIL_ImageOps = ImageOps
            self._pillow_available = True
        except ImportError:
            print("[WARN] Pillow not installed")

        try:
            import numpy as np
            self._np = np
            self._numpy_available = True
        except ImportError:
            print("[WARN] numpy not installed")

        # PyMuPDF for direct PDF text extraction
        self._fitz_available = False
        try:
            import fitz
            self._fitz = fitz
            self._fitz_available = True
            print("[OCR] PyMuPDF (fitz) available for PDF text extraction")
        except ImportError:
            print("[WARN] PyMuPDF (fitz) not installed")

    async def close(self):
        pass

    def _build_unreadable_response(self, minutes, reason="unreadable"):
        print(f"[SKIP] Skipping LLM call — text is {reason}")
        return SummaryResponse(
            minutes_id=minutes.id,
            meeting_date=minutes.meeting_date,
            meeting_type=minutes.meeting_type,
            summary=(
                "The document text could not be reliably extracted. "
                "The scanned document images did not produce readable text "
                f"({reason}). Please view the original document directly."
            ),
            key_decisions=[], budget_items=[], public_comment_opportunities=[], items=[],
        )

    async def _call_groq(self, system_prompt, user_content, max_tokens=4096):
        """Call Groq chat completions directly via httpx (async). No OpenAI SDK needed.
        
        Validates all responses, handles errors gracefully, and provides detailed
        logging for debugging API issues.
        """
        import httpx, traceback
        url = "https://api.groq.com/openai/v1/chat/completions"
        headers = {
            "Authorization": f"Bearer {self.grok_key}",
            "Content-Type": "application/json",
            "User-Agent": "OpenCouncil/1.0",
        }
        payload = {
            "model": self.text_model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_content},
            ],
            "temperature": 0.0,
            "max_tokens": max_tokens,
        }
        try:
            async with httpx.AsyncClient(timeout=120.0) as client:
                resp = await client.post(url, json=payload, headers=headers)
                status = resp.status_code
                body = resp.text
                print(f"[GROQ] HTTP {status}, response_len={len(body)}")
                
                # Check HTTP status code
                if status != 200:
                    print(f"[GROQ] Error {status}: {body[:500]}")
                    try:
                        error_data = resp.json()
                        if "error" in error_data:
                            print(f"[GROQ] Error details: {error_data['error']}")
                    except:
                        pass
                    return None
                
                # Parse JSON response
                try:
                    data = resp.json()
                except Exception as e:
                    print(f"[GROQ] Failed to parse JSON: {e}")
                    print(f"[GROQ] Response body: {body[:300]}")
                    return None
                
                # Validate response structure
                if not isinstance(data, dict):
                    print(f"[GROQ] Invalid response structure: {type(data)}")
                    return None
                
                # Check for choices
                choices = data.get("choices", [])
                if not choices:
                    print(f"[GROQ] No choices in response")
                    print(f"[GROQ] Response keys: {list(data.keys())}")
                    return None
                
                # Extract message content
                first_choice = choices[0]
                if not isinstance(first_choice, dict):
                    print(f"[GROQ] Invalid choice structure: {type(first_choice)}")
                    return None
                
                message = first_choice.get("message", {})
                if not isinstance(message, dict):
                    print(f"[GROQ] Invalid message structure: {type(message)}")
                    return None
                
                content = message.get("content", "")
                if not isinstance(content, str):
                    print(f"[GROQ] Content is not string: {type(content)}")
                    return None
                
                if not content.strip():
                    print(f"[GROQ] Empty content in response")
                    return None
                
                return content.strip()
                
        except httpx.TimeoutException:
            print(f"[GROQ] Request timed out after 120 seconds")
            return None
        except httpx.ConnectError as e:
            print(f"[GROQ] Connection error: {e}")
            return None
        except Exception as e:
            tb = traceback.format_exc()
            print(f"[GROQ] Exception: {e}")
            print(f"[GROQ] Traceback: {tb[:500]}")
            return None

    async def summarize_minutes(self, minutes, image_fetcher=None):
        """Summarize city council minutes using robust text extraction pipeline.

        Flow:
        1. If raw_text exists and is meaningful -> use text mode (fast)
        2. If page images available -> try PDF text extraction -> try OCR.space -> try EasyOCR/Tesseract
        3. Otherwise -> fallback to text mode (may produce stub response)

        Returns SummaryResponse with extracted data, or a stub response if
        the document cannot be processed.
        """
        # Prefer text mode when raw_text has meaningful content (much faster - avoids OCR)
        has_text = minutes.raw_text and len(minutes.raw_text.strip()) > 100
        if has_text:
            stub_patterns = ["this document is a scanned image", "page images are available at the following urls", "no detailed minutes text available"]
            is_stub = any(p in minutes.raw_text.lower() for p in stub_patterns)
            if not is_stub:
                print(f"[PIPELINE] Skipping OCR - using existing raw_text ({len(minutes.raw_text)} chars)")
                return await self._summarize_with_text(minutes)

        # Check if we have page images to OCR
        has_page_urls = minutes.page_image_urls and len(minutes.page_image_urls) > 0
        print(f"[PIPELINE] has_text={bool(has_text)}, has_page_urls={has_page_urls}, image_fetcher={image_fetcher is not None}")

        if has_page_urls:
            print(f"[PIPELINE] Attempting text extraction on {len(minutes.page_image_urls)} pages")
            return await self._summarize_with_ocr(minutes, image_fetcher)

        # No images, fallback to text mode
        print(f"[PIPELINE] No page images found, using text mode")
        return await self._summarize_with_text(minutes)

    async def _extract_text_from_pdf_bytes(self, pdf_bytes: bytes) -> Optional[str]:
        """Extract text directly from PDF bytes using PyMuPDF.
        
        Works on digital PDFs (not scanned images).
        Returns extracted text or None if extraction fails or produces no meaningful text.
        """
        if not self._fitz_available or not pdf_bytes:
            return None
        
        if pdf_bytes[:4] != b'%PDF':
            return None
        
        try:
            pdf_doc = self._fitz.open(stream=pdf_bytes, filetype="pdf")
            text_parts = []
            total_chars = 0
            
            for page_num in range(len(pdf_doc)):
                page = pdf_doc[page_num]
                page_text = page.get_text().strip()
                if page_text and len(page_text) > 20:
                    text_parts.append(f"--- Page {page_num + 1} ---\n{page_text}")
                    total_chars += len(page_text)
            
            pdf_doc.close()
            
            if total_chars > 100:  # Meaningful text
                print(f"[PDF-TEXT] Extracted {total_chars} chars from {len(text_parts)} pages")
                return "\n\n".join(text_parts)[:self.MAX_OCR_TEXT_CHARS]
            else:
                print(f"[PDF-TEXT] Only {total_chars} chars extracted - likely scanned image PDF, need OCR")
                return None
                
        except Exception as e:
            print(f"[PDF-TEXT] Extraction failed: {e}")
            return None

    async def _ocr_with_easyocr(self, image_bytes: bytes) -> str:
        """OCR using EasyOCR (local, no API key needed).
        
        Best quality local OCR engine. Works with any image format.
        """
        if not self._easyocr_available:
            return ""
        
        try:
            if self._easyocr_reader is None:
                print("[OCR] Initializing EasyOCR reader (may take a moment)...")
                self._easyocr_reader = self._easyocr.Reader(
                    self.EASYOCR_LANGUAGES,
                    gpu=False,
                    verbose=False,
                )
            
            # Convert bytes to numpy array
            img = self._PIL_Image.open(io.BytesIO(image_bytes))
            img_array = self._np.array(img)
            
            results = self._easyocr_reader.readtext(img_array)
            text = " ".join([r[1] for r in results if r[2] > 0.3])  # Confidence > 30%
            
            if text and len(text.strip()) > 20:
                print(f"[EASYOCR] Extracted {len(text.strip())} chars")
                return text.strip()
            return ""
        except Exception as e:
            print(f"[EASYOCR] Failed: {e}")
            return ""

    async def _ocr_with_tesseract(self, image_bytes: bytes) -> str:
        """OCR using Tesseract (local, open source).
        
        Falls back after OCR.space and EasyOCR.
        """
        if not self._pytesseract_available or not self._pillow_available:
            return ""
        
        try:
            img = self._PIL_Image.open(io.BytesIO(image_bytes))
            # Preprocess: convert to grayscale, increase contrast
            if img.mode != 'L':
                img = img.convert('L')
            # Apply threshold to improve OCR
            img = self._PIL_ImageOps.autocontrast(img, cutoff=5)
            text = self._pytesseract.image_to_string(
                img,
                lang=self.TESSERACT_LANGUAGES,
                config='--oem 3 --psm 6',
            )
            if text and len(text.strip()) > 20:
                print(f"[TESSERACT] Extracted {len(text.strip())} chars")
                return text.strip()
            return ""
        except Exception as e:
            print(f"[TESSERACT] Failed: {e}")
            return ""

    async def _ocr_with_ocrspace(self, image_bytes):
        """Free OCR.space API — no API key needed, 25k requests/month.
        
        Validates image format and size before uploading.
        Handles API errors gracefully with detailed error messages.
        Uses async httpx to avoid blocking the event loop.
        """
        import httpx
        
        # Validate image bytes
        if not image_bytes:
            print("[OCR.SPACE] Error: No image bytes provided")
            return ""
        
        if len(image_bytes) > 10 * 1024 * 1024:  # 10MB limit
            if self._pillow_available:
                try:
                    img = self._PIL_Image.open(io.BytesIO(image_bytes))
                    if img.mode != 'RGB':
                        img = img.convert('RGB')
                    img.thumbnail((1920, 2560))
                    buf = io.BytesIO()
                    img.save(buf, format='PNG', optimize=True)
                    image_bytes = buf.getvalue()
                    print(f"[OCR.SPACE] Compressed to {len(image_bytes)} bytes")
                except Exception as e:
                    print(f"[OCR.SPACE] Compression failed: {e}")
        
        try:
            img_b64 = base64.b64encode(image_bytes).decode("utf-8")
            
            async with httpx.AsyncClient(timeout=60.0) as client:
                resp = await client.post(
                    "https://api.ocr.space/parse/image",
                    data={
                        "base64Image": f"data:image/png;base64,{img_b64}",
                        "language": "eng",
                        "isOverlayRequired": False,
                        "OCREngine": 2,
                    },
                    headers={"apikey": "helloworld"},
                )
                
                if resp.status_code != 200:
                    print(f"[OCR.SPACE] HTTP {resp.status_code}: {resp.text[:200]}")
                    return ""
                
                data = resp.json()
                
                if data.get("IsErroredOnProcessing"):
                    print(f"[OCR.SPACE] API Error: {data.get('ErrorMessage')}")
                    return ""
                
                parsed_results = data.get("ParsedResults", [])
                if not parsed_results:
                    return ""
                
                parsed_text = parsed_results[0].get("ParsedText", "")
                if not parsed_text or len(parsed_text.strip()) < 20:
                    return ""
                
                return parsed_text.strip()
            
        except Exception as e:
            print(f"[OCR.SPACE] Exception: {e}")
            return ""

    async def _ocr_all_pages(self, image_bytes_list: list[bytes]) -> list[tuple[int, str]]:
        """Run all OCR engines on all pages and return best results.
        
        For each page, tries: OCR.space -> EasyOCR -> Tesseract
        Returns list of (page_number, text) tuples.
        """
        results = []
        
        for i, img_bytes in enumerate(image_bytes_list):
            page_num = i + 1
            page_text = ""
            
            # Try OCR.space first (best quality for scanned docs)
            print(f"[OCR] Page {page_num}: Trying OCR.space...")
            page_text = await self._ocr_with_ocrspace(img_bytes)
            
            # Fallback to EasyOCR
            if not page_text and self._easyocr_available:
                print(f"[OCR] Page {page_num}: OCR.space failed, trying EasyOCR...")
                page_text = await self._ocr_with_easyocr(img_bytes)
            
            # Fallback to Tesseract
            if not page_text and self._pytesseract_available:
                print(f"[OCR] Page {page_num}: EasyOCR failed, trying Tesseract...")
                page_text = await self._ocr_with_tesseract(img_bytes)
            
            if page_text and len(page_text.strip()) > 20:
                results.append((page_num, page_text.strip()))
                print(f"[OCR] Page {page_num}: {len(page_text.strip())} chars extracted")
            else:
                print(f"[OCR] Page {page_num}: No text extracted by any OCR engine")
        
        return results

    async def _summarize_with_ocr(self, minutes, image_fetcher=None):
        """Three-tier OCR pipeline: 
        1. Try PDF text extraction (fastest, works on digital PDFs)
        2. Multi-engine OCR on all pages (OCR.space -> EasyOCR -> Tesseract)
        3. Fallback to text mode with page URLs
        """
        has_urls = minutes.page_image_urls and isinstance(minutes.page_image_urls[0], str)
        
        # --- TIER 1: Try direct PDF text extraction ---
        # If page_image_urls point to PDFs, try extracting text directly
        if has_urls:
            pdf_urls = [u for u in minutes.page_image_urls if u.lower().endswith('.pdf') or '.pdf?' in u.lower()]
            if pdf_urls and image_fetcher:
                try:
                    # image_fetcher may download PDFs and render them as images
                    # For PDFs, try direct text extraction first
                    import httpx
                    async with httpx.AsyncClient(timeout=30.0) as client:
                        for pdf_url in pdf_urls[:3]:  # Try first 3 PDF URLs
                            try:
                                resp = await client.get(pdf_url, follow_redirects=True)
                                if resp.status_code == 200 and resp.content[:4] == b'%PDF':
                                    pdf_text = await self._extract_text_from_pdf_bytes(resp.content)
                                    if pdf_text:
                                        print(f"[OCR] Extracted text directly from PDF ({len(pdf_text)} chars)")
                                        minutes.raw_text = pdf_text
                                        return await self._summarize_with_text(minutes)
                            except Exception:
                                continue
                except Exception:
                    pass

        # --- Get page images for OCR ---
        image_bytes_list = []
        if has_urls and image_fetcher:
            try:
                image_bytes_list = await image_fetcher()
                print(f"[OCR] Downloaded {len(image_bytes_list)} page images")
            except Exception as e:
                print(f"[WARN] Failed to download images: {e}")
        elif not has_urls:
            image_bytes_list = [b for b in minutes.page_image_urls if isinstance(b, bytes)]

        if not image_bytes_list:
            print("[OCR] No images, falling back to text mode")
            return await self._summarize_with_text(minutes)

        # --- TIER 2: OCR all pages with all engines ---
        print(f"[OCR] Processing {len(image_bytes_list)} pages with OCR pipeline...")
        ocr_results = await self._ocr_all_pages(image_bytes_list)

        if ocr_results:
            # Build full text from all pages
            ocr_parts = [f"--- Page {p[0]} ---\n{p[1]}" for p in ocr_results]
            full_text = "\n\n".join(ocr_parts)
            minutes.raw_text = full_text
            print(f"[OCR] Total: {len(full_text)} chars from {len(ocr_results)} pages")
            
            # Check if we got meaningful text
            meaningful = self._count_meaningful_chars(full_text)
            if meaningful > 200:
                return await self._call_groq_and_parse(minutes, full_text)
            else:
                print(f"[OCR] Only {meaningful} meaningful chars - text may be garbled")
                return await self._summarize_with_text(minutes)

        # Last resort: text mode
        print("[OCR] All OCR methods failed, falling back to text mode")
        return await self._summarize_with_text(minutes)

    def _count_meaningful_chars(self, text: str) -> int:
        """Count characters that are actual words (not just symbols/garbage)."""
        words = text.split()
        meaningful = sum(len(w) for w in words if any(c.isalpha() for c in w))
        return meaningful

    async def _call_groq_and_parse(self, minutes, full_text):
        """Call Groq API with extracted text and parse the JSON response."""
        user_content = (
            f"Please summarize the following city council meeting minutes "
            f"for {minutes.city}, {minutes.state} on "
            f"{minutes.meeting_date.strftime('%B %d, %Y')}.\n\n"
            f"Meeting Type: {minutes.meeting_type}\n"
            f"Title: {minutes.title}\n\n"
            f"The following text was extracted from scanned document images:\n\n"
            f"{full_text[:self.MAX_OCR_TEXT_CHARS]}\n\n"
            f"Return ONLY valid JSON matching the specified structure. "
            f"Do not include any text outside the JSON object."
        )

        raw_content = await self._call_groq(
            MINUTES_SYSTEM_PROMPT + "\n\nIMPORTANT: Return ONLY valid JSON. Do not include any text outside the JSON object.",
            user_content,
            max_tokens=4096,
        )
        if raw_content is None:
            print(f"[OCR] Groq API call failed")
            return self._build_unreadable_response(minutes, reason="groq-api-failed")

        print(f"[GROQ] Raw response length: {len(raw_content)}")
        
        # Extract JSON from response, handling code blocks
        json_content = raw_content.strip()
        if "```json" in json_content:
            try:
                json_content = json_content.split("```json")[1].split("```")[0].strip()
            except IndexError:
                pass
        elif "```" in json_content:
            try:
                json_content = json_content.split("```")[1].split("```")[0].strip()
            except IndexError:
                pass
        
        try:
            result = json.loads(json_content)
            if not isinstance(result, dict):
                print(f"[GROQ] JSON root is not dict: {type(result)}")
                return self._build_unreadable_response(minutes, reason="groq-invalid-structure")
        except json.JSONDecodeError as e:
            print(f"[GROQ] JSON parse error at position {e.pos}: {e.msg}")
            print(f"[GROQ] Raw response (first 500 chars): {raw_content[:500]}")
            return self._build_unreadable_response(minutes, reason="groq-json-parse-error")

        return SummaryResponse(
            minutes_id=minutes.id,
            meeting_date=minutes.meeting_date,
            meeting_type=minutes.meeting_type,
            big_picture=result.get("big_picture", ""),
            summary=result.get("summary", "No summary available."),
            key_decisions=[d if isinstance(d, dict) else {"description": d} for d in result.get("key_decisions", [])],
            budget_items=[d if isinstance(d, dict) else {"description": d} for d in result.get("budget_items", [])],
            public_comment_opportunities=[d if isinstance(d, dict) else {"description": d} for d in result.get("public_comment_opportunities", [])],
            items=[d if isinstance(d, dict) else {"description": d} for d in result.get("items", [])],
            what_you_can_do=[d if isinstance(d, dict) else {"description": d} for d in result.get("what_you_can_do", [])],
        )

    async def _summarize_with_text(self, minutes):
        """Summarize using Groq text model via direct httpx."""
        minutes_text = self._prepare_minutes_text(minutes)
        stub_indicators = ["this document is a scanned image", "ocr text extraction was not available", "no detailed minutes text available"]
        if any(indicator in minutes_text.lower() for indicator in stub_indicators):
            print("[TEXT] Stub text detected, skipping LLM")
            return self._build_unreadable_response(minutes, reason="scanned document image without OCR text extraction")

        user_content = (
            f"Please summarize the following city council meeting minutes "
            f"for {minutes.city}, {minutes.state} on "
            f"{minutes.meeting_date.strftime('%B %d, %Y')}.\n\n"
            f"Meeting Type: {minutes.meeting_type}\n"
            f"Title: {minutes.title}\n\n"
            f"Minutes Text:\n{minutes_text}\n\n"
            f"Return ONLY valid JSON matching the specified structure. "
            f"Do not include any text outside the JSON object."
        )

        raw_content = await self._call_groq(
            MINUTES_SYSTEM_PROMPT + "\n\nIMPORTANT: Return ONLY valid JSON. Do not include any text outside the JSON object.",
            user_content,
            max_tokens=2000,
        )
        if raw_content is None:
            print(f"[TEXT] Groq API call failed")
            return self._build_unreadable_response(minutes, reason="groq-api-failed")

        print(f"[TEXT] Groq response length: {len(raw_content)}")
        
        # Extract JSON from response, handling code blocks
        json_content = raw_content.strip()
        if "```json" in json_content:
            try:
                json_content = json_content.split("```json")[1].split("```")[0].strip()
            except IndexError:
                pass
        elif "```" in json_content:
            try:
                json_content = json_content.split("```")[1].split("```")[0].strip()
            except IndexError:
                pass
        
        try:
            result = json.loads(json_content)
            if not isinstance(result, dict):
                print(f"[TEXT] JSON root is not dict: {type(result)}")
                return self._build_unreadable_response(minutes, reason="groq-invalid-structure")
        except json.JSONDecodeError as e:
            print(f"[TEXT] JSON parse error at position {e.pos}: {e.msg}")
            print(f"[TEXT] Raw response (first 500 chars): {raw_content[:500]}")
            return self._build_unreadable_response(minutes, reason="groq-json-parse-error")

        return SummaryResponse(
            minutes_id=minutes.id,
            meeting_date=minutes.meeting_date,
            meeting_type=minutes.meeting_type,
            big_picture=result.get("big_picture", ""),
            summary=result.get("summary", "No summary available."),
            key_decisions=[d if isinstance(d, dict) else {"description": d} for d in result.get("key_decisions", [])],
            budget_items=[d if isinstance(d, dict) else {"description": d} for d in result.get("budget_items", [])],
            public_comment_opportunities=[d if isinstance(d, dict) else {"description": d} for d in result.get("public_comment_opportunities", [])],
            items=[d if isinstance(d, dict) else {"description": d} for d in result.get("items", [])],
            what_you_can_do=[d if isinstance(d, dict) else {"description": d} for d in result.get("what_you_can_do", [])],
        )

    def _prepare_minutes_text(self, minutes):
        parts = [f"Meeting: {minutes.title}", f"Date: {minutes.meeting_date.strftime('%B %d, %Y')}", f"Type: {minutes.meeting_type}", ""]
        if minutes.raw_text:
            raw = minutes.raw_text.strip()
            stub_patterns = ["this document is a scanned image", "page images are available at the following urls", "no detailed minutes text available"]
            is_stub = any(p in raw.lower() for p in stub_patterns)
            if is_stub:
                parts.append("(This document is a scanned image. OCR text extraction was not available in this environment. Please view the original document directly.)")
            else:
                parts.append("--- Full Minutes Text ---")
                parts.append(raw[:self.MAX_OCR_TEXT_CHARS])
        else:
            parts.append("(No detailed minutes text available)")
        return "\n".join(parts)