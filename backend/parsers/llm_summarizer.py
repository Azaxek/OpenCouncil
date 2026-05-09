"""
LLM-powered summarization pipeline for Civic City Hub.

Takes meeting minutes text or scanned document images and produces:
- Plain-language summary of what happened at the meeting
- Key decisions with explanations
- Budget/financial items highlighted
- Public comment opportunities
- Per-item plain-language translations

Supports two modes:
1. Text-based summarization (DeepSeek) — for documents with extractable text
2. OCR-based summarization (Tesseract + DeepSeek) — for scanned document images (TIFF)
   This is completely free and open-source, no API keys needed beyond DeepSeek.
"""

import io
import json
import os
from typing import Awaitable, Callable, Optional

from openai import OpenAI

from models.schemas import Minutes, SummaryResponse


# System prompt for minutes summarization — EXTREMELY STRICT to prevent hallucination
MINUTES_SYSTEM_PROMPT = """You are a civic technology assistant that helps residents understand
what happened at their local government meetings. Your job is to translate official city council
meeting minutes into plain, accessible language.

## ABSOLUTE RULE — ZERO HALLUCINATION

You MUST follow these rules STRICTLY. Violating them will cause real-world harm.

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

The text you receive may be extracted from scanned documents using OCR (Optical Character
Recognition). OCR frequently introduces errors: misspelled words, missing punctuation,
incorrect numbers, garbled text, and missing sections. Treat OCR text as potentially
unreliable — only report what you can read with high confidence.

Format your response as JSON with this structure:
{
  "summary": "2-3 paragraph plain-language overview. If text quality is poor, state that clearly.",
  "key_decisions": [
    {
      "title": "Short title (ONLY if explicitly in text)",
      "plain_english": "What this means in simple terms",
      "impact": "Who this affects and how",
      "category": "zoning|budget|public-safety|infrastructure|administration|other",
      "vote": "Only include if vote tally is explicitly recorded in text"
    }
  ],
  "budget_items": [
    {
      "title": "Item title (ONLY if explicitly in text)",
      "amount": "Exact amount from text (ONLY if explicitly stated)",
      "description": "What the money is for"
    }
  ],
  "public_comment_opportunities": [
    {
      "item": "Topic discussed (ONLY if explicitly in text)",
      "deadline": "When comments were received (ONLY if explicitly stated)",
      "how": "How residents provided input (ONLY if explicitly stated)"
    }
  ],
  "items": [
    {
      "title": "Topic discussed (ONLY if explicitly in text)",
      "plain_english": "Plain language explanation",
      "category": "section category",
      "action_needed": "approved|denied|tabled|discussed|received"
    }
  ]
}

REMEMBER: If the text does not contain specific information for any field, return `[]`
for that field. Empty arrays are CORRECT. Fabricated data is WRONG."""


class LLMSummarizer:
    """Summarizes city council minutes using LLM APIs.

    Supports two modes:
    - Text mode (DeepSeek): For documents with extractable text content
    - OCR mode (Tesseract + DeepSeek): For scanned document images (TIFF) from Laserfiche
      Uses free, open-source Tesseract OCR to extract text from images,
      then passes the text to DeepSeek for summarization.

    Falls back to text mode if no page images are available.
    """

    def __init__(
        self,
        deepseek_key: Optional[str] = None,
        text_model: str = "deepseek-chat",
    ):
        self.deepseek_key = deepseek_key or os.getenv("DEEPSEEK_API_KEY")
        self.text_model = text_model

        # Initialize DeepSeek client (text mode)
        if self.deepseek_key:
            self.deepseek_client = OpenAI(
                api_key=self.deepseek_key,
                base_url="https://api.deepseek.com",
            )
        else:
            self.deepseek_client = None

        if not self.deepseek_key:
            raise ValueError(
                "DEEPSEEK_API_KEY is required. "
                "Set it as an environment variable or pass to the constructor."
            )

        # Try to import Tesseract OCR (optional dependency)
        self._pytesseract_available = False
        self._pillow_available = False
        try:
            import pytesseract
            self._pytesseract = pytesseract
            self._pytesseract_available = True
        except ImportError:
            print(
                "[WARN] pytesseract not installed. "
                "OCR mode will be unavailable for scanned images. "
                "Install with: pip install pytesseract"
            )

        try:
            from PIL import Image
            self._PIL_Image = Image
            self._pillow_available = True
        except ImportError:
            print(
                "[WARN] Pillow not installed. "
                "OCR mode will be unavailable for scanned images. "
                "Install with: pip install Pillow"
            )

    async def close(self):
        """Cleanup resources (no-op for now, kept for API compatibility)."""
        pass

    async def summarize_minutes(
        self,
        minutes: Minutes,
        image_fetcher: Optional[Callable[[], Awaitable[list[bytes]]]] = None,
    ) -> SummaryResponse:
        """Summarize meeting minutes using the best available method.

        Priority:
        1. OCR mode (Tesseract) — if page_image_urls are available and
           pytesseract is installed. This reads scanned document images for free.
           If image bytes aren't already in page_image_urls, uses image_fetcher
           to download them.
        2. Text mode (DeepSeek) — if raw_text is available.

        Args:
            minutes: The minutes document to summarize.
            image_fetcher: Optional callable that returns list of image bytes
                for OCR. Used when page_image_urls contains URLs (strings)
                instead of actual image data.
        """
        # Prefer OCR mode for scanned document images
        if minutes.page_image_urls and self._pytesseract_available and self._pillow_available:
            return await self._summarize_with_ocr(minutes, image_fetcher)

        # Fall back to text mode
        if self.deepseek_client:
            return await self._summarize_with_text(minutes)

        raise RuntimeError("No LLM client available for summarization.")

    async def _summarize_with_ocr(
        self,
        minutes: Minutes,
        image_fetcher: Optional[Callable[[], Awaitable[list[bytes]]]] = None,
    ) -> SummaryResponse:
        """Summarize minutes using Tesseract OCR on scanned document images.

        Downloads each page image, runs Tesseract OCR to extract text,
        then passes the extracted text to DeepSeek for summarization.

        This is completely free and open-source — no paid API keys needed.
        """
        # Determine if we have URLs or actual image data
        has_urls = (
            minutes.page_image_urls
            and isinstance(minutes.page_image_urls[0], str)
        )

        # Fetch image bytes if needed
        image_bytes_list: list[bytes] = []
        if has_urls and image_fetcher:
            try:
                image_bytes_list = await image_fetcher()
                print(
                    f"[OCR] Downloaded {len(image_bytes_list)} page images"
                )
            except Exception as e:
                print(
                    f"[WARN] Failed to download page images: {e}"
                )
        elif not has_urls:
            # Already bytes
            image_bytes_list = [
                b for b in minutes.page_image_urls
                if isinstance(b, bytes)
            ]

        if not image_bytes_list:
            print(
                "[WARN] No image data available for OCR, "
                "falling back to text mode"
            )
            if self.deepseek_client:
                return await self._summarize_with_text(minutes)
            raise RuntimeError(
                "OCR failed: no image data and no text fallback."
            )

        # Run OCR on each page image
        extracted_pages = []
        for i, img_bytes in enumerate(image_bytes_list):
            try:
                image = self._PIL_Image.open(io.BytesIO(img_bytes))

                # Run Tesseract OCR
                text = self._pytesseract.image_to_string(
                    image, lang="eng"
                )

                if text and text.strip():
                    extracted_pages.append(
                        f"--- Page {i + 1} ---\n{text.strip()}"
                    )
                    print(
                        f"[OCR] Page {i + 1}: extracted "
                        f"{len(text.strip())} characters"
                    )
                    # Log first 200 chars of each page for debugging
                    print(
                        f"[OCR] Page {i + 1} preview: "
                        f"{text.strip()[:200]}"
                    )
                else:
                    print(
                        f"[OCR] Page {i + 1}: no text extracted"
                    )

            except Exception as e:
                print(
                    f"[WARN] OCR failed for page {i + 1}: {e}"
                )

        if not extracted_pages:
            print(
                "[WARN] OCR produced no text, falling back to text mode"
            )
            if self.deepseek_client:
                return await self._summarize_with_text(minutes)
            raise RuntimeError(
                "OCR failed to extract text and no text fallback available."
            )

        # Combine all extracted text
        full_text = "\n\n".join(extracted_pages)

        # Save OCR text to minutes.raw_text so it persists and can be inspected
        minutes.raw_text = full_text
        print(f"[OCR] Total extracted text: {len(full_text)} characters")
        print(f"[OCR] Full extracted text:\n{full_text[:3000]}")

        # Now summarize with DeepSeek — temperature 0.0 for maximum determinism
        user_content = (
            f"Please summarize the following city council meeting minutes "
            f"for {minutes.city}, {minutes.state} on "
            f"{minutes.meeting_date.strftime('%B %d, %Y')}.\n\n"
            f"Meeting Type: {minutes.meeting_type}\n"
            f"Title: {minutes.title}\n\n"
            f"The following text was extracted from scanned document images "
            f"using OCR. Some errors may be present.\n\n"
            f"Extracted Text:\n{full_text[:15000]}\n\n"
            f"Return ONLY valid JSON matching the specified structure."
        )

        response = self.deepseek_client.chat.completions.create(
            model=self.text_model,
            messages=[
                {"role": "system", "content": MINUTES_SYSTEM_PROMPT},
                {"role": "user", "content": user_content},
            ],
            temperature=0.0,
            max_tokens=2000,
            response_format={"type": "json_object"},
        )

        result = json.loads(response.choices[0].message.content)

        return SummaryResponse(
            minutes_id=minutes.id,
            meeting_date=minutes.meeting_date,
            meeting_type=minutes.meeting_type,
            summary=result.get("summary", "No summary available."),
            key_decisions=result.get("key_decisions", []),
            budget_items=result.get("budget_items", []),
            public_comment_opportunities=result.get(
                "public_comment_opportunities", []
            ),
            items=result.get("items", []),
        )

    async def _summarize_with_text(
        self, minutes: Minutes
    ) -> SummaryResponse:
        """Summarize minutes using DeepSeek text model."""
        minutes_text = self._prepare_minutes_text(minutes)

        user_content = (
            f"Please summarize the following city council meeting minutes "
            f"for {minutes.city}, {minutes.state} on "
            f"{minutes.meeting_date.strftime('%B %d, %Y')}.\n\n"
            f"Meeting Type: {minutes.meeting_type}\n"
            f"Title: {minutes.title}\n\n"
            f"Minutes Text:\n{minutes_text}\n\n"
            f"Return ONLY valid JSON matching the specified structure."
        )

        response = self.deepseek_client.chat.completions.create(
            model=self.text_model,
            messages=[
                {"role": "system", "content": MINUTES_SYSTEM_PROMPT},
                {"role": "user", "content": user_content},
            ],
            temperature=0.3,
            max_tokens=2000,
            response_format={"type": "json_object"},
        )

        result = json.loads(response.choices[0].message.content)

        return SummaryResponse(
            minutes_id=minutes.id,
            meeting_date=minutes.meeting_date,
            meeting_type=minutes.meeting_type,
            summary=result.get("summary", "No summary available."),
            key_decisions=result.get("key_decisions", []),
            budget_items=result.get("budget_items", []),
            public_comment_opportunities=result.get(
                "public_comment_opportunities", []
            ),
            items=result.get("items", []),
        )

    def _prepare_minutes_text(self, minutes: Minutes) -> str:
        """Prepare minutes data as text for the LLM."""
        parts = [f"Meeting: {minutes.title}"]
        parts.append(f"Date: {minutes.meeting_date.strftime('%B %d, %Y')}")
        parts.append(f"Type: {minutes.meeting_type}")
        parts.append("")

        if minutes.raw_text:
            # Use the raw document text if available
            parts.append("--- Full Minutes Text ---")
            parts.append(minutes.raw_text[:12000])  # Limit length
        else:
            parts.append("(No detailed minutes text available)")

        return "\n".join(parts)
