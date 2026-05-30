"""
LLM-powered summarization pipeline for OpenCouncil.
... (full file content follows)
"""

import io
import json
import os
import re
import sys
from typing import Awaitable, Callable, Optional

from openai import OpenAI

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
    """Summarizes city council minutes using LLM APIs."""

    MAX_OCR_TEXT_CHARS = 30000
    EASYOCR_LANGUAGES = ['en', 'fr']
    TESSERACT_LANGUAGES = "eng+fra"
    GARBLED_THRESHOLD = 0.3
    UNREADABLE_THRESHOLD = 0.0
    MIN_OCR_CHARS = 50

    def __init__(self, grok_key=None, text_model="llama-3.1-8b-instant"):
        self.grok_key = grok_key or os.getenv("GROK_API_KEY")
        self.text_model = text_model
        if self.grok_key:
            self.deepseek_client = OpenAI(api_key=self.grok_key, base_url="https://api.groq.com/openai/v1")
        else:
            self.deepseek_client = None
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

    async def summarize_minutes(self, minutes, image_fetcher=None):
        ocr_capable = self._easyocr_available or self._pytesseract_available or self._pillow_available
        if minutes.page_image_urls:
            if ocr_capable:
                return await self._summarize_with_ocr(minutes, image_fetcher)
            else:
                print("[OCR] No local OCR, trying image download anyway...")
                if image_fetcher:
                    try:
                        image_bytes = await image_fetcher()
                        if image_bytes:
                            return await self._summarize_with_ocr(minutes, image_fetcher)
                    except Exception as e:
                        print(f"[WARN] Image download failed: {e}")
        if self.deepseek_client:
            return await self._summarize_with_text(minutes)
        raise RuntimeError("No LLM client available.")

    def _ocr_with_ocrspace(self, image_bytes):
        """Free OCR.space API — no API key needed, 25k requests/month."""
        import base64
        import httpx
        img_b64 = base64.b64encode(image_bytes).decode("utf-8")
        try:
            resp = httpx.post(
                "https://api.ocr.space/parse/image",
                data={
                    "base64Image": f"data:image/png;base64,{img_b64}",
                    "language": "eng",
                    "isOverlayRequired": False,
                    "OCREngine": 2,
                },
                headers={"apikey": "helloworld"},
                timeout=30.0,
            )
            if resp.status_code == 200:
                data = resp.json()
                if data.get("IsErroredOnProcessing"):
                    print(f"[OCR.SPACE] Error: {data.get('ErrorMessage')}")
                    return ""
                parsed = data.get("ParsedResults", [])
                if parsed:
                    return parsed[0].get("ParsedText", "")
        except Exception as e:
            print(f"[OCR.SPACE] Failed: {e}")
        return ""

    async def _summarize_with_ocr(self, minutes, image_fetcher=None):
        """Primary OCR path: OCR.space (free) -> EasyOCR -> Tesseract -> Vision -> Text fallback"""
        has_urls = minutes.page_image_urls and isinstance(minutes.page_image_urls[0], str)

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
            if self.deepseek_client:
                return await self._summarize_with_text(minutes)
            raise RuntimeError("No image data and no text fallback.")

        # Use free OCR.space API to extract text from scanned images.
        # Works on Vercel Lambda with no local binaries needed.
        # Rate limit: 25k requests/month free tier, no API key required.
        print("[OCR] Extracting text via free OCR.space API...")
        ocr_parts = []
        for i, img_bytes in enumerate(image_bytes_list[:5]):
            page_text = self._ocr_with_ocrspace(img_bytes)
            if page_text and len(page_text.strip()) > 20:
                ocr_parts.append(f"--- Page {i + 1} ---\n{page_text.strip()}")
                print(f"[OCR] Page {i + 1}: {len(page_text.strip())} chars")
            else:
                print(f"[OCR] Page {i + 1}: OCR.space returned no text")

        if ocr_parts:
            full_text = "\n\n".join(ocr_parts)
            minutes.raw_text = full_text
            print(f"[OCR] Total: {len(full_text)} chars from OCR.space")

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

            response = self.deepseek_client.chat.completions.create(
                model=self.text_model,
                messages=[
                    {"role": "system", "content": MINUTES_SYSTEM_PROMPT},
                    {"role": "user", "content": user_content},
                ],
                temperature=0.0,
                max_tokens=4096,
                response_format={"type": "json_object"},
            )

            result = json.loads(response.choices[0].message.content)
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

        # Last resort: text mode
        print("[OCR] All OCR methods failed, falling back to text mode")
        if self.deepseek_client:
            return await self._summarize_with_text(minutes)
        raise RuntimeError("All OCR methods and text fallback failed.")

    async def _summarize_with_text(self, minutes):
        """Summarize using Groq text model."""
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

        response = self.deepseek_client.chat.completions.create(
            model=self.text_model,
            messages=[{"role": "system", "content": MINUTES_SYSTEM_PROMPT}, {"role": "user", "content": user_content}],
            temperature=0.0, max_tokens=2000, response_format={"type": "json_object"},
        )
        result = json.loads(response.choices[0].message.content)
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