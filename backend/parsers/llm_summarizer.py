"""
LLM-powered summarization pipeline for OpenCouncil.

Takes meeting minutes text or scanned document images and produces:
- Plain-language summary of what happened at the meeting
- Key decisions with explanations
- Budget/financial items highlighted
- Public comment opportunities
- Per-item plain-language translations

Supports two modes:
1. Text-based summarization (Groq / Llama 8B) — for documents with extractable text
2. OCR-based summarization (Tesseract + Groq) — for scanned document images (TIFF)
   OCR is completely free and open-source; Groq provides 14,400 req/day free tier.
"""

import io
import json
import os
import re
import sys
from typing import Awaitable, Callable, Optional

from openai import OpenAI

from models.schemas import Minutes, SummaryResponse


# System prompt for minutes summarization — STRICT to prevent hallucination
# Designed to handle OCR-garbled text from scanned city council minutes
# CRITICAL: LLMs naturally hallucinate when given sparse/garbled text.
# This prompt is structured to prefer "nothing found" over "made up",
# while still extracting whatever information IS available from noisy OCR.
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
   |------------------------|----------------------|
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
  "big_picture": "ONE sentence that captures the overall vibe of the meeting. Example: 'Tonight's meeting was all about cleaning up the city — from building new houses to regulating messy donation boxes and honoring our local history at Lake Crook.'",

  "summary": "2-3 paragraph plain-language overview. Focus on CITIZEN IMPACT — how each decision affects residents' wallets, homes, or daily lives. If text quality is poor, state that clearly.",

  "key_decisions": [
    {
      "title": "Short title of the decision (e.g. 'Tax break for new homes on empty lots')",
      "plain_english": "What was decided, explained in plain language. Translate government terms. Focus on what it means for residents.",
      "impact": "How this affects a resident's wallet, property, or daily life. Example: 'If you live near Polk or Houston St., expect to see new construction soon. This program turns empty lots into new homes, which usually helps your neighborhood's property value.'",
      "category": "Use Life-Centric labels: 'Your Neighborhood', 'Your Tax Dollars', 'City Calendar', 'Your Commute', 'Your Utilities', 'Your Parks & Trails', 'Your Safety', 'Meeting Logistics', 'Community Briefing', 'City Planning', 'Council Action'"
    }
  ],

  "budget_items": [
    {
      "title": "Short name of the budget item (e.g. 'Street Repair Fund')",
      "amount": "Optional: dollar amount if explicitly stated (e.g. '$50,000'). Omit if not present.",
      "description": "What the budget item is for, in plain language. Explain what it means for residents."
    }
  ],

  "public_comment_opportunities": [
    {
      "item": "Description of the public comment opportunity or comments made",
      "deadline": "Optional: deadline for submitting comments if mentioned. Omit if not present.",
      "how": "Optional: how to submit comments (e.g. 'In person at City Hall', 'Email the City Clerk'). Omit if not stated."
    }
  ],

  "items": [
    {
      "title": "Short title of the agenda item (e.g. 'Call to Order', 'Tax break for new homes')",
      "plain_english": "Description of what happened for this item, in plain language",
      "category": "Use Life-Centric labels: 'Your Neighborhood', 'Your Tax Dollars', 'City Calendar', 'Your Commute', 'Your Utilities', 'Your Parks & Trails', 'Your Safety', 'Meeting Logistics', 'Community Briefing', 'City Planning', 'Council Action'",
      "action_needed": "Optional: what action, if any, residents need to take (e.g. 'Visit the park this summer to see the new historical markers', 'Have a cluttered donation box in your area? The city is about to start requiring permits.'). Omit if none."
    }
  ],

  "what_you_can_do": [
    {
      "action": "A specific, actionable step a resident can take based on this meeting. Example: 'Visit Lake Crook this summer to see the new historical markers once they are installed.'",
      "who": "Optional: who this action is for (e.g. 'Nearby residents', 'Homeowners', 'Anyone interested in local history'). Omit if for everyone."
    }
  ]
}

IMPORTANT: Every item in every array MUST be a JSON object with the EXACT field names shown above.
NEVER return plain strings in arrays. If you have no information for a section, return [].
REMEMBER: Empty arrays are CORRECT. Fabricated data is WRONG. If in doubt, return empty arrays."""


class LLMSummarizer:
    """Summarizes city council minutes using LLM APIs.

    Supports three modes (in priority order):
    1. EasyOCR mode (primary): Deep-learning based OCR (MIT license).
       Significantly better accuracy than Tesseract on scanned documents.
       Supports English + French natively.
    2. Tesseract OCR mode (fallback): For scanned document images (TIFF) from Laserfiche.
       Free, open-source, used when EasyOCR is not available.
    3. Text mode (Groq / Llama 8B): For documents with extractable text content.
       Uses Groq API (OpenAI-compatible) — 14,400 free requests/day on Llama 8B.

    Falls back to text mode if no page images are available.
    """

    # Maximum characters to send to the LLM from OCR text
    MAX_OCR_TEXT_CHARS = 30000

    # OCR languages for Paris, TX — English + French for French-influenced names
    # EasyOCR uses ['en', 'fr'] format, Tesseract uses 'eng+fra' format
    EASYOCR_LANGUAGES = ['en', 'fr']
    TESSERACT_LANGUAGES = "eng+fra"

    # Garbled text detection thresholds
    # If quality score is below GARBLED_THRESHOLD, a quality warning is added to the prompt
    GARBLED_THRESHOLD = 0.3
    # If quality score is below UNREADABLE_THRESHOLD, skip LLM entirely and return canned response.
    # Set to 0.0 to NEVER skip the LLM — the system prompt already handles garbled text
    # by telling the LLM to return empty arrays rather than hallucinate.
    # The LLM is far better at extracting partial meaning from noisy OCR than any heuristic.
    UNREADABLE_THRESHOLD = 0.0

    # Minimum character threshold for considering OCR successful.
    # If an engine produces fewer chars than this, other engines will still be tried.
    MIN_OCR_CHARS = 50

    def __init__(
        self,
        grok_key: Optional[str] = None,
        text_model: str = "llama-3.1-8b-instant",
    ):
        self.grok_key = grok_key or os.getenv("GROK_API_KEY")
        self.text_model = text_model

        # Initialize Groq client via OpenAI-compatible SDK
        if self.grok_key:
            self.deepseek_client = OpenAI(
                api_key=self.grok_key,
                base_url="https://api.groq.com/openai/v1",
            )
        else:
            self.deepseek_client = None

        if not self.grok_key:
            raise ValueError(
                "GROK_API_KEY is required. "
                "Set it as an environment variable or pass to the constructor."
            )

        # --- Initialize OCR engines ---

        # 1. EasyOCR (primary) — deep-learning based, MIT license, better than Tesseract
        self._easyocr_available = False
        self._easyocr_reader = None
        try:
            import easyocr
            # Lazy-init: create reader on first use to avoid slow startup
            self._easyocr = easyocr
            self._easyocr_available = True
            print("[OCR] EasyOCR available (primary OCR engine)")
        except ImportError:
            print(
                "[WARN] easyocr not installed. "
                "Install with: pip install easyocr"
            )

        # 2. Tesseract OCR (fallback) — traditional OCR engine
        self._pytesseract_available = False
        self._pillow_available = False
        self._numpy_available = False
        try:
            import pytesseract

            # On Windows, set the Tesseract executable path if not already set
            if sys.platform == "win32":
                tesseract_paths = [
                    r"C:\Program Files\Tesseract-OCR\tesseract.exe",
                    r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe",
                ]
                for tp in tesseract_paths:
                    if os.path.exists(tp):
                        pytesseract.pytesseract.tesseract_cmd = tp
                        print(f"[OCR] Tesseract found at: {tp}")
                        break

            self._pytesseract = pytesseract
            self._pytesseract_available = True
        except ImportError:
            print(
                "[WARN] pytesseract not installed. "
                "Tesseract fallback OCR unavailable. "
                "Install with: pip install pytesseract"
            )

        # 3. Pillow — required for image preprocessing
        try:
            from PIL import Image, ImageFilter, ImageEnhance, ImageOps
            self._PIL_Image = Image
            self._PIL_ImageFilter = ImageFilter
            self._PIL_ImageEnhance = ImageEnhance
            self._PIL_ImageOps = ImageOps
            self._pillow_available = True
        except ImportError:
            print(
                "[WARN] Pillow not installed. "
                "Image preprocessing disabled. "
                "Install with: pip install Pillow"
            )

        # 4. NumPy — for advanced image preprocessing
        try:
            import numpy as np
            self._np = np
            self._numpy_available = True
        except ImportError:
            print("[WARN] numpy not installed. Advanced image preprocessing disabled.")

    async def close(self):
        """Cleanup resources (no-op for now, kept for API compatibility)."""
        pass

    def _preprocess_image_for_ocr(self, image, for_easyocr: bool = False):
        """Preprocess a PIL image to improve OCR accuracy.

        Applies:
        1. Upscale 2x (improves Tesseract accuracy on low-DPI scans)
        2. Convert to grayscale
        3. Adaptive contrast enhancement (CLAHE-like via local equalization)
        4. Apply sharpening filter
        5. Gentle denoise with small median filter
        6. Deskew (straighten rotated scans)
        7. Adaptive binarization (Otsu's method) for Tesseract
        8. Morphological cleanup (close small gaps in characters)

        For EasyOCR, returns the preprocessed image in RGB mode (EasyOCR needs 3-channel)
        but WITHOUT aggressive binarization — EasyOCR's deep learning model works best
        with continuous-tone grayscale images, not harshly thresholded ones.

        For Tesseract, returns the preprocessed image in grayscale (L) mode with
        adaptive binarization for maximum OCR accuracy.

        Args:
            image: PIL Image to preprocess.
            for_easyocr: If True, returns RGB image without binarization;
                        if False, returns grayscale with binarization.

        Returns:
            Preprocessed PIL Image.
        """
        # Step 1: Upscale 2x for better OCR on low-DPI scans
        # Laserfiche page images are typically ~72 DPI; Tesseract works best at 300+ DPI
        orig_w, orig_h = image.size
        if orig_w < 1500 and orig_h < 2000:
            scale = max(2, min(4, 2400 // min(orig_w, orig_h)))
            image = image.resize((orig_w * scale, orig_h * scale), self._PIL_Image.LANCZOS)
        elif orig_w < 2500 and orig_h < 3500:
            image = image.resize((orig_w * 2, orig_h * 2), self._PIL_Image.LANCZOS)

        # Step 2: Convert to grayscale for processing
        if image.mode != "L":
            image = image.convert("L")

        # Step 3: Adaptive contrast enhancement
        # Use local contrast normalization instead of global contrast stretch
        if self._numpy_available:
            try:
                img_array = self._np.array(image, dtype=self._np.float64)
                # Apply CLAHE-like effect: local mean normalization
                # Divide image into tiles and equalize each
                h, w = img_array.shape
                tile_h, tile_w = max(32, h // 8), max(32, w // 8)
                # Simple local contrast stretch using percentile-based scaling
                low_pct = self._np.percentile(img_array, 5)
                high_pct = self._np.percentile(img_array, 95)
                if high_pct > low_pct:
                    img_array = (img_array - low_pct) / (high_pct - low_pct) * 255.0
                    img_array = self._np.clip(img_array, 0, 255).astype(self._np.uint8)
                    image = self._PIL_Image.fromarray(img_array, mode="L")
            except Exception:
                # Fallback to simple contrast enhancement
                enhancer = self._PIL_ImageEnhance.Contrast(image)
                image = enhancer.enhance(2.0)
        else:
            enhancer = self._PIL_ImageEnhance.Contrast(image)
            image = enhancer.enhance(2.0)

        # Step 4: Apply sharpening filter
        image = image.filter(self._PIL_ImageFilter.SHARPEN)

        # Step 5: Gentle denoise — use size=3 for median filter (removes salt-and-pepper
        # without destroying thin strokes like punctuation)
        image = image.filter(self._PIL_ImageFilter.MedianFilter(size=3))

        # Step 6: Deskew — straighten slightly rotated scans
        if self._numpy_available and not for_easyocr:
            try:
                from scipy import ndimage as ndi
                img_array = self._np.array(image)
                # Find skew angle by projecting horizontal lines
                # Invert so text is white on black for projection
                binary = self._np.where(img_array > 128, 1, 0)
                # Try angles from -5 to +5 degrees
                best_angle = 0.0
                best_variance = 0.0
                for angle in self._np.arange(-5.0, 5.5, 0.5):
                    rotated = ndi.rotate(binary, angle, reshape=False, order=0)
                    # Project horizontally (sum each row)
                    h_proj = self._np.sum(rotated, axis=1)
                    # Variance of projection — higher = more aligned text lines
                    variance = self._np.var(h_proj)
                    if variance > best_variance:
                        best_variance = variance
                        best_angle = angle
                if abs(best_angle) > 0.3:
                    # Apply deskew to original grayscale image
                    img_array = ndi.rotate(img_array, best_angle, reshape=False, order=1, cval=255)
                    img_array = self._np.clip(img_array, 0, 255).astype(self._np.uint8)
                    image = self._PIL_Image.fromarray(img_array, mode="L")
            except ImportError:
                pass  # scipy not available, skip deskew
            except Exception:
                pass  # deskew failed silently

        # Step 7: Binarize ONLY for Tesseract — EasyOCR works better with grayscale
        if not for_easyocr:
            if self._numpy_available:
                try:
                    img_array = self._np.array(image)
                    # Use Otsu's adaptive threshold instead of fixed 128
                    # Otsu finds the optimal threshold by minimizing intra-class variance
                    hist, _ = self._np.histogram(img_array, bins=256, range=(0, 256))
                    total = img_array.size
                    sum_total = self._np.dot(self._np.arange(256), hist)
                    sum_bg = 0.0
                    weight_bg = 0.0
                    max_variance = 0.0
                    optimal_threshold = 128
                    for t in range(256):
                        weight_bg += hist[t]
                        if weight_bg == 0:
                            continue
                        weight_fg = total - weight_bg
                        if weight_fg == 0:
                            break
                        sum_bg += t * hist[t]
                        mean_bg = sum_bg / weight_bg
                        mean_fg = (sum_total - sum_bg) / weight_fg
                        # Between-class variance
                        variance = weight_bg * weight_fg * (mean_bg - mean_fg) ** 2
                        if variance > max_variance:
                            max_variance = variance
                            optimal_threshold = t
                    img_array = self._np.where(img_array > optimal_threshold, 255, 0).astype(self._np.uint8)

                    # Step 8: Morphological cleanup — close small gaps in characters
                    # Use a 2x2 kernel to dilate then erode (close operation)
                    from scipy import ndimage as ndi_morph
                    kernel = self._np.ones((2, 2), dtype=self._np.uint8)
                    # Dilation: grow white regions (text)
                    img_array = ndi_morph.binary_dilation(img_array, structure=kernel).astype(self._np.uint8) * 255
                    # Erosion: shrink back to original size (removes noise)
                    img_array = ndi_morph.binary_erosion(img_array, structure=kernel).astype(self._np.uint8) * 255

                    image = self._PIL_Image.fromarray(img_array, mode="L")
                except ImportError:
                    # scipy not available for morphology, use simple threshold
                    image = image.point(lambda x: 255 if x > 128 else 0)
                except Exception:
                    # Fallback to simple threshold
                    image = image.point(lambda x: 255 if x > 128 else 0)
            else:
                # Simple threshold without numpy
                image = image.point(lambda x: 255 if x > 128 else 0)

        # Convert to RGB if needed for EasyOCR
        if for_easyocr:
            image = image.convert("RGB")

        return image

    def _get_easyocr_reader(self):
        """Lazy-initialize EasyOCR reader.

        EasyOCR downloads model files on first use (~100MB for English+French).
        We cache the reader instance to avoid re-downloading on every call.
        """
        if self._easyocr_reader is None and self._easyocr_available:
            try:
                print("[OCR] Initializing EasyOCR reader (downloading models if needed)...")
                self._easyocr_reader = self._easyocr.Reader(
                    self.EASYOCR_LANGUAGES,
                    gpu=False,  # CPU mode for HF Spaces
                    verbose=False,
                )
                print("[OCR] EasyOCR reader initialized successfully")
            except Exception as e:
                print(f"[WARN] Failed to initialize EasyOCR reader: {e}")
                self._easyocr_available = False
        return self._easyocr_reader

    @staticmethod
    def _extract_easyocr_results(results: list) -> list[str]:
        """Extract text from EasyOCR results, handling multiple return formats.

        EasyOCR's readtext() can return different formats depending on version
        and whether paragraph=True is used:
        - Format A (default): [(bbox, text, confidence), ...]
        - Format B (paragraph=True in some versions): [(text, confidence), ...]
        - Format C: [text, ...]  (rare, edge case)

        Args:
            results: Raw results from reader.readtext()

        Returns:
            List of extracted text strings, filtered by confidence > 0.3 when available.
        """
        lines = []
        for result in results:
            try:
                if isinstance(result, str):
                    # Format C: just a string
                    lines.append(result.strip())
                elif isinstance(result, (list, tuple)):
                    if len(result) == 3:
                        # Format A: (bbox, text, confidence)
                        text, confidence = result[1], result[2]
                        if confidence > 0.3:
                            lines.append(text.strip())
                    elif len(result) == 2:
                        # Format B: (text, confidence) — paragraph mode
                        text, confidence = result
                        if confidence > 0.3:
                            lines.append(text.strip())
                    elif len(result) == 1:
                        # Edge case: (text,) — no confidence
                        lines.append(str(result[0]).strip())
            except Exception:
                continue
        return lines

    def _ocr_with_easyocr(self, image_bytes: bytes) -> str:
        """Run EasyOCR on a single page image with preprocessing.

        EasyOCR is a deep-learning based OCR engine (MIT license) that
        significantly outperforms Tesseract on scanned documents.

        Applies image preprocessing (contrast enhancement, binarization)
        before passing to EasyOCR for better results on scanned documents.

        Args:
            image_bytes: PNG/JPEG bytes of the page image.

        Returns:
            Extracted text string, or empty string on failure.
        """
        reader = self._get_easyocr_reader()
        if reader is None:
            return ""

        try:
            # Open the image
            image = self._PIL_Image.open(io.BytesIO(image_bytes))

            # Preprocess the image for better OCR accuracy
            # EasyOCR gets the same preprocessing as Tesseract now
            processed = self._preprocess_image_for_ocr(image, for_easyocr=True)

            # EasyOCR expects a numpy array (H, W, 3) in RGB format
            img_array = self._np.array(processed)

            # Run EasyOCR — try paragraph mode first, fall back to non-paragraph
            try:
                results = reader.readtext(img_array, paragraph=True)
                lines = self._extract_easyocr_results(results)
            except Exception:
                # Fallback: try without paragraph mode
                results = reader.readtext(img_array, paragraph=False)
                lines = self._extract_easyocr_results(results)

            easyocr_text = "\n".join(lines)

            # If EasyOCR produced very little text, try without preprocessing too
            # (some documents OCR better with original image)
            if len(easyocr_text.strip()) < self.MIN_OCR_CHARS:
                raw_image = self._PIL_Image.open(io.BytesIO(image_bytes))
                if raw_image.mode != "RGB":
                    raw_image = raw_image.convert("RGB")
                raw_array = self._np.array(raw_image)
                try:
                    raw_results = reader.readtext(raw_array, paragraph=True)
                    raw_lines = self._extract_easyocr_results(raw_results)
                except Exception:
                    raw_results = reader.readtext(raw_array, paragraph=False)
                    raw_lines = self._extract_easyocr_results(raw_results)
                raw_text = "\n".join(raw_lines)
                if len(raw_text.strip()) > len(easyocr_text.strip()):
                    print(f"[EASYOCR] Raw image produced more text ({len(raw_text.strip())} chars) than preprocessed ({len(easyocr_text.strip())} chars)")
                    easyocr_text = raw_text

            return easyocr_text
        except Exception as e:
            print(f"[EASYOCR] Error during OCR: {e}")
            return ""

    def _detect_garbled_text(self, text: str) -> tuple[bool, float]:
        """Detect if OCR text is garbled/unreadable.

        Returns (is_garbled, confidence_score) where confidence_score is
        0.0 (completely garbled) to 1.0 (clean text).

        Checks:
        - Ratio of alphabetic characters
        - Average word length
        - Frequency of repeated characters
        - Frequency of non-alphanumeric symbols

        NOTE: This is a SOFT guard — it only adds a warning to the LLM prompt.
        The UNREADABLE_THRESHOLD is set to 0.0 so the LLM always gets a chance
        to extract meaning from noisy OCR text. The system prompt already handles
        garbled text by telling the LLM to return empty arrays rather than hallucinate.
        """
        if not text or not text.strip():
            return True, 0.0

        # Count various character types — use the full text (not stripped)
        # to get accurate ratios including whitespace
        total_chars = len(text)
        if total_chars == 0:
            return True, 0.0

        alpha_chars = sum(1 for c in text if c.isalpha())
        digit_chars = sum(1 for c in text if c.isdigit())
        space_chars = sum(1 for c in text if c.isspace())
        symbol_chars = sum(1 for c in text if not c.isalnum() and not c.isspace())

        # Use non-space chars as denominator for alpha/symbol ratios
        # (spaces inflate total_chars and dilute the ratios)
        nonspace_chars = total_chars - space_chars
        alpha_ratio = alpha_chars / nonspace_chars if nonspace_chars > 0 else 0
        symbol_ratio = symbol_chars / nonspace_chars if nonspace_chars > 0 else 0

        # Check for long unbroken strings (no spaces)
        words = text.split()
        if words:
            avg_word_len = sum(len(w) for w in words) / len(words)
            max_word_len = max(len(w) for w in words)
        else:
            avg_word_len = 0
            max_word_len = 0

        # Check for repeated character patterns (OCR artifact)
        repeated_patterns = len(re.findall(r'(.)\1{3,}', text))

        # Scoring — start at 1.0 (perfect) and penalize
        score = 1.0

        # Penalize low alpha ratio (should be >60% for English text)
        if alpha_ratio < 0.3:
            score -= 0.3
        elif alpha_ratio < 0.5:
            score -= 0.15

        # Penalize high symbol ratio
        if symbol_ratio > 0.4:
            score -= 0.2
        elif symbol_ratio > 0.25:
            score -= 0.1

        # Penalize very long average words (OCR merging words)
        if avg_word_len > 20:
            score -= 0.2
        elif avg_word_len > 15:
            score -= 0.1

        # Penalize extremely long words
        if max_word_len > 40:
            score -= 0.15

        # Penalize repeated character patterns
        if repeated_patterns > 10:
            score -= 0.15

        # Penalize very short text
        if total_chars < 100:
            score -= 0.2
        elif total_chars < 200:
            score -= 0.1

        # Clamp score to [0.0, 1.0]
        score = max(0.0, min(1.0, score))

        is_garbled = score < self.GARBLED_THRESHOLD

        if is_garbled:
            print(f"[OCR QUALITY] Text appears garbled (score: {score:.2f}): "
                  f"alpha_ratio={alpha_ratio:.2f}, symbol_ratio={symbol_ratio:.2f}, "
                  f"avg_word_len={avg_word_len:.1f}, max_word_len={max_word_len}, "
                  f"repeated_patterns={repeated_patterns}")

        return is_garbled, score

    def _build_unreadable_response(
        self, minutes: Minutes, reason: str = "unreadable"
    ) -> SummaryResponse:
        """Build a minimal SummaryResponse for unreadable/garbled text.

        This avoids calling the LLM at all when text quality is too poor,
        since LLMs tend to hallucinate when given sparse or garbled input.
        """
        print(f"[SKIP] Skipping LLM call — text is {reason}")
        return SummaryResponse(
            minutes_id=minutes.id,
            meeting_date=minutes.meeting_date,
            meeting_type=minutes.meeting_type,
            summary=(
                f"The document text could not be reliably extracted. "
                f"The scanned document images did not produce readable text "
                f"({reason}). Please view the original document directly."
            ),
            key_decisions=[],
            budget_items=[],
            public_comment_opportunities=[],
            items=[],
        )

    async def summarize_minutes(
        self,
        minutes: Minutes,
        image_fetcher: Optional[Callable[[], Awaitable[list[bytes]]]] = None,
    ) -> SummaryResponse:
        """Summarize meeting minutes using the best available method.

        Priority:
        1. OCR mode (EasyOCR -> Tesseract) — for scanned document images.
        2. Text mode (DeepSeek) — if raw_text is available.

        OCR mode is entered when:
        - page_image_urls is non-empty, AND
        - At least one OCR engine is available (EasyOCR, Tesseract, or Pillow for preprocessing)

        If OCR engines aren't available but page images exist (e.g. on Hugging Face
        where Tesseract isn't installed), we still try to download images and run OCR.
        If that fails, we fall back to text mode with whatever raw_text is available.

        Args:
            minutes: The minutes document to summarize.
            image_fetcher: Optional callable that returns list of image bytes
                for OCR. Used when page_image_urls contains URLs (strings)
                instead of actual image data.
        """
        # Check if any OCR capability is available
        ocr_capable = (
            self._easyocr_available
            or self._pytesseract_available
            or self._pillow_available
        )

        # Prefer OCR mode for scanned document images
        if minutes.page_image_urls:
            if ocr_capable:
                return await self._summarize_with_ocr(minutes, image_fetcher)
            else:
                # No local OCR engines available (e.g. Hugging Face).
                # Try to download images anyway — if successful, we can still
                # attempt OCR. If not, fall through to text mode.
                print("[OCR] No local OCR engines available, trying image download anyway...")
                if image_fetcher:
                    try:
                        image_bytes = await image_fetcher()
                        if image_bytes:
                            # We have images but no OCR — try OCR mode anyway
                            # (it will attempt OCR and fall back gracefully)
                            return await self._summarize_with_ocr(minutes, image_fetcher)
                    except Exception as e:
                        print(f"[WARN] Image download failed (expected on HF): {e}")

        # Fall back to text mode
        if self.deepseek_client:
            return await self._summarize_with_text(minutes)

        raise RuntimeError("No LLM client available for summarization.")

    async def _summarize_with_llm_vision(
        self,
        minutes: Minutes,
        image_bytes_list: list[bytes],
    ) -> SummaryResponse:
        """Summarize minutes by sending page images directly to Groq's vision API.

        On Vercel Lambda, local OCR engines (EasyOCR, Tesseract) are not available.
        Groq's Llama 3.2 11B Vision model can read text from images directly,
        bypassing the need for local OCR entirely.

        Args:
            minutes: The minutes document to summarize.
            image_bytes_list: List of PNG/JPEG bytes for each page image.

        Returns:
            SummaryResponse with AI-generated summary.
        """
        import base64

        # Build content with images (first 5 pages to stay within rate limits)
        max_pages = min(len(image_bytes_list), 5)
        content_parts = [
            {
                "type": "text",
                "text": (
                    f"Please summarize the following city council meeting minutes "
                    f"for {minutes.city}, {minutes.state} on "
                    f"{minutes.meeting_date.strftime('%B %d, %Y')}.\n\n"
                    f"Meeting Type: {minutes.meeting_type}\n"
                    f"Title: {minutes.title}\n\n"
                    f"These are scanned document pages (images). "
                    f"Read the text from each image and summarize the meeting.\n\n"
                    f"Return ONLY valid JSON matching the specified structure. "
                    f"Do not include any text outside the JSON object."
                ),
            }
        ]

        for i in range(max_pages):
            img_b64 = base64.b64encode(image_bytes_list[i]).decode("utf-8")
            # Determine MIME type from first bytes (PNG header or JPEG header)
            if image_bytes_list[i][:4] == b'\x89PNG':
                mime = "image/png"
            else:
                mime = "image/jpeg"
            content_parts.append({
                "type": "image_url",
                "image_url": {"url": f"data:{mime};base64,{img_b64}"},
            })

        # Use Llama 3.2 11B Vision (supports image inputs)
        response = self.deepseek_client.chat.completions.create(
            model="llama-3.2-11b-vision-preview",
            messages=[
                {"role": "system", "content": MINUTES_SYSTEM_PROMPT},
                {"role": "user", "content": content_parts},
            ],
            temperature=0.0,
            max_tokens=8096,
            response_format={"type": "json_object"},
        )

        raw = response.choices[0].message.content
        try:
            data = json.loads(raw)
            data["minutes_id"] = minutes.id
            data["meeting_date"] = minutes.meeting_date
            data["meeting_type"] = minutes.meeting_type
            return SummaryResponse(**data)
        except (json.JSONDecodeError, TypeError) as e:
            print(f"[VISION] Failed to parse LLM response: {e}")
            return self._build_unreadable_response(
                minutes, reason=f"vision-parse-failed"
            )

    async def _summarize_with_ocr(
        self,
        minutes: Minutes,
        image_fetcher: Optional[Callable[[], Awaitable[list[bytes]]]] = None,
    ) -> SummaryResponse:
        """Summarize minutes using OCR on scanned document images.

        Priority:
        1. Groq Vision API (server-side, no local OCR needed) — free with API key
        2. EasyOCR (primary local) — deep-learning based, MIT license
        3. Tesseract (fallback) — traditional OCR

        On Vercel Lambda (no local OCR binaries), Groq Vision does all the work
        by sending page images directly to the LLM which reads the text.
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
            image_bytes_list = [
                b for b in minutes.page_image_urls
                if isinstance(b, bytes)
            ]

        if not image_bytes_list:
            print("[WARN] No image data available for OCR, falling back to text mode")
            if self.deepseek_client:
                return await self._summarize_with_text(minutes)
            raise RuntimeError("OCR failed: no image data and no text fallback.")

        # ALWAYS try Groq Vision API first — it's free (uses existing API key),
        # works on any platform, and reads text from images better than local OCR.
        # This is the primary path on Vercel Lambda where OCR binaries don't exist.
        try:
            print("[VISION] Using Groq Vision API to read text from images")
            result = await self._summarize_with_llm_vision(minutes, image_bytes_list)
            # Check if Vision got meaningful content
            if result.summary and "could not be reliably" not in result.summary:
                return result
            print("[VISION] Vision returned limited content, trying local OCR as supplement...")
        except Exception as e:
            print(f"[VISION] Groq Vision failed: {e}, trying local OCR fallback...")

        # Run OCR on each page image (only if local OCR engines exist)
        extracted_pages = []
        total_raw_chars = 0

        for i, img_bytes in enumerate(image_bytes_list):
            page_text = ""
            ocr_engine = "none"

            try:
                best_text = ""
                best_engine = "none"

                # --- Try EasyOCR first (deep-learning, better accuracy) ---
                if self._easyocr_available:
                    try:
                        text_easy = self._ocr_with_easyocr(img_bytes)
                        if text_easy and len(text_easy.strip()) > len(best_text.strip()):
                            best_text = text_easy.strip()
                            best_engine = "EasyOCR"
                            print(f"[OCR] Page {i + 1}: EasyOCR extracted {len(best_text)} chars")
                    except Exception as e:
                        print(f"[WARN] EasyOCR failed for page {i + 1}: {e}")

                # --- Try Tesseract too ---
                if self._pytesseract_available:
                    try:
                        image = self._PIL_Image.open(io.BytesIO(img_bytes))
                        processed = self._preprocess_image_for_ocr(image, for_easyocr=False)

                        tess_psm_modes = [6, 4, 3, 1]
                        tess_results = []

                        for psm in tess_psm_modes:
                            try:
                                text = self._pytesseract.image_to_string(
                                    processed,
                                    lang=self.TESSERACT_LANGUAGES,
                                    config=f"--psm {psm} --oem 3",
                                ).strip()
                                if text:
                                    tess_results.append((text, psm))
                            except Exception:
                                continue

                        try:
                            text_raw = self._pytesseract.image_to_string(
                                image, lang=self.TESSERACT_LANGUAGES,
                                config="--psm 6 --oem 3",
                            ).strip()
                            if text_raw:
                                tess_results.append((text_raw, 0))
                        except Exception:
                            pass

                        text_tess = ""
                        best_tess_psm = -1
                        for text_candidate, psm_mode in tess_results:
                            if len(text_candidate) > len(text_tess):
                                alpha_count = sum(1 for c in text_candidate if c.isalpha())
                                if alpha_count > 10 or len(text_candidate) > len(text_tess) * 2:
                                    text_tess = text_candidate
                                    best_tess_psm = psm_mode

                        if text_tess and len(text_tess) > len(best_text):
                            best_text = text_tess
                            best_engine = f"Tesseract(PSM{best_tess_psm})" if best_tess_psm > 0 else "Tesseract(raw)"
                            print(f"[OCR] Page {i + 1}: {best_engine} extracted {len(best_text)} chars")
                    except Exception as e:
                        print(f"[WARN] Tesseract failed for page {i + 1}: {e}")

                if best_text:
                    page_text = best_text
                    ocr_engine = best_engine

                if page_text and page_text.strip():
                    total_raw_chars += len(page_text.strip())
                    extracted_pages.append(
                        f"--- Page {i + 1} ({ocr_engine}) ---\n{page_text.strip()}"
                    )
                    print(f"[OCR] Page {i + 1} ({ocr_engine}) preview: {page_text.strip()[:300]}")
                else:
                    print(f"[OCR] Page {i + 1}: no text extracted by any OCR engine")

            except Exception as e:
                print(f"[WARN] OCR failed for page {i + 1}: {e}")

        if not extracted_pages:
            print("[WARN] OCR produced no text, falling back to text mode")
            if self.deepseek_client:
                return await self._summarize_with_text(minutes)
            raise RuntimeError("OCR failed to extract text and no text fallback available.")

        # Combine all extracted text
        full_text = "\n\n".join(extracted_pages)
        is_garbled, quality_score = self._detect_garbled_text(full_text)
        print(f"[OCR QUALITY] Overall text quality score: {quality_score:.2f} {'GARBLED' if is_garbled else 'OK'}")

        minutes.raw_text = full_text
        print(f"[OCR] Total extracted text: {len(full_text)} characters")

        if quality_score < self.UNREADABLE_THRESHOLD:
            return self._build_unreadable_response(
                minutes, reason=f"OCR quality score too low ({quality_score:.2f})"
            )

        text_for_llm = full_text[:self.MAX_OCR_TEXT_CHARS]

        quality_warning = ""
        if is_garbled:
            quality_warning = (
                "\n\nWARNING: The OCR-extracted text below appears to be of poor quality "
                "(garbled, incomplete, or unreadable). Please be EXTREMELY conservative in "
                "your interpretation. Only report information you can read with very high "
                "confidence. If most of the text is unreadable, state that clearly in the summary."
            )

        user_content = (
            f"Please summarize the following city council meeting minutes "
            f"for {minutes.city}, {minutes.state} on "
            f"{minutes.meeting_date.strftime('%B %d, %Y')}.\n\n"
            f"Meeting Type: {minutes.meeting_type}\n"
            f"Title: {minutes.title}\n\n"
            f"The following text was extracted from scanned document images "
            f"using OCR. Some errors may be present."
            f"{quality_warning}\n\n"
            f"Extracted Text:\n{text_for_llm}\n\n"
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
            max_tokens=2000,
        )

        result = json.loads(response.choices[0].message.content)

        # Guard: ensure all list fields contain dicts, not strings
        # The LLM sometimes returns plain strings instead of {"description": "..."} objects
        def _ensure_dict_list(items: list) -> list[dict]:
            """Convert string items to dicts if needed."""
            cleaned = []
            for item in items:
                if isinstance(item, str):
                    cleaned.append({"description": item})
                elif isinstance(item, dict):
                    cleaned.append(item)
            return cleaned

        return SummaryResponse(
            minutes_id=minutes.id,
            meeting_date=minutes.meeting_date,
            meeting_type=minutes.meeting_type,
            big_picture=result.get("big_picture", ""),
            summary=result.get("summary", "No summary available."),
            key_decisions=_ensure_dict_list(result.get("key_decisions", [])),
            budget_items=_ensure_dict_list(result.get("budget_items", [])),
            public_comment_opportunities=_ensure_dict_list(
                result.get("public_comment_opportunities", [])
            ),
            items=_ensure_dict_list(result.get("items", [])),
            what_you_can_do=_ensure_dict_list(result.get("what_you_can_do", [])),
        )

    async def _summarize_with_text(
        self, minutes: Minutes
    ) -> SummaryResponse:
        """Summarize minutes using Groq (Llama 8B) text model."""
        minutes_text = self._prepare_minutes_text(minutes)

        # Detect garbled text quality
        is_garbled, quality_score = self._detect_garbled_text(minutes_text)
        print(f"[TEXT QUALITY] Text quality score: {quality_score:.2f} "
              f"({'GARBLED' if is_garbled else 'OK'})")

        # PRE-LLM GUARD: If text quality is below UNREADABLE_THRESHOLD, skip LLM entirely.
        # LLMs hallucinate when given sparse/garbled text — better to return empty response.
        if quality_score < self.UNREADABLE_THRESHOLD:
            return self._build_unreadable_response(
                minutes, reason=f"text quality score too low ({quality_score:.2f})"
            )

        # STUB TEXT DETECTION: If the prepared text indicates this is a scanned image
        # with no OCR-extracted content, skip the LLM entirely.
        # Sending stub text to the LLM causes it to echo back the "not available" message
        # as if it were a real summary, which is misleading.
        stub_indicators = [
            "this document is a scanned image",
            "ocr text extraction was not available",
            "no detailed minutes text available",
        ]
        minutes_text_lower = minutes_text.lower()
        is_stub = any(indicator in minutes_text_lower for indicator in stub_indicators)
        if is_stub:
            print("[TEXT] Detected stub text (scanned image without OCR), skipping LLM")
            return self._build_unreadable_response(
                minutes, reason="scanned document image without OCR text extraction"
            )

        quality_warning = ""
        if is_garbled:
            quality_warning = (
                "\n\nWARNING: The text below appears to be of poor quality "
                "(garbled, incomplete, or unreadable). Please be EXTREMELY conservative in "
                "your interpretation. Only report information you can read with very high "
                "confidence. If most of the text is unreadable, state that clearly in the summary."
            )

        user_content = (
            f"Please summarize the following city council meeting minutes "
            f"for {minutes.city}, {minutes.state} on "
            f"{minutes.meeting_date.strftime('%B %d, %Y')}.\n\n"
            f"Meeting Type: {minutes.meeting_type}\n"
            f"Title: {minutes.title}\n\n"
            f"Minutes Text:\n{minutes_text}\n"
            f"{quality_warning}\n\n"
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
            max_tokens=2000,
        )

        result = json.loads(response.choices[0].message.content)

        # Guard: ensure all list fields contain dicts, not strings
        def _ensure_dict_list(items: list) -> list[dict]:
            """Convert string items to dicts if needed."""
            cleaned = []
            for item in items:
                if isinstance(item, str):
                    cleaned.append({"description": item})
                elif isinstance(item, dict):
                    cleaned.append(item)
            return cleaned

        return SummaryResponse(
            minutes_id=minutes.id,
            meeting_date=minutes.meeting_date,
            meeting_type=minutes.meeting_type,
            big_picture=result.get("big_picture", ""),
            summary=result.get("summary", "No summary available."),
            key_decisions=_ensure_dict_list(result.get("key_decisions", [])),
            budget_items=_ensure_dict_list(result.get("budget_items", [])),
            public_comment_opportunities=_ensure_dict_list(
                result.get("public_comment_opportunities", [])
            ),
            items=_ensure_dict_list(result.get("items", [])),
            what_you_can_do=_ensure_dict_list(result.get("what_you_can_do", [])),
        )

    def _prepare_minutes_text(self, minutes: Minutes) -> str:
        """Prepare minutes data as text for the LLM."""
        parts = [f"Meeting: {minutes.title}"]
        parts.append(f"Date: {minutes.meeting_date.strftime('%B %d, %Y')}")
        parts.append(f"Type: {minutes.meeting_type}")
        parts.append("")

        if minutes.raw_text:
            raw = minutes.raw_text.strip()

            # Detect stub text from fetch_document_text() — this is NOT real content
            # Stub text looks like: "[This document is a scanned image...]"
            stub_patterns = [
                "this document is a scanned image",
                "page images are available at the following urls",
                "no detailed minutes text available",
            ]
            is_stub = any(p in raw.lower() for p in stub_patterns)

            if is_stub:
                # Don't send stub text to the LLM — it will just hallucinate
                parts.append(
                    "(This document is a scanned image. "
                    "OCR text extraction was not available in this environment. "
                    "Please view the original document directly.)"
                )
            else:
                # Use the raw document text if available
                parts.append("--- Full Minutes Text ---")
                parts.append(raw[:self.MAX_OCR_TEXT_CHARS])
        else:
            parts.append("(No detailed minutes text available)")

        return "\n".join(parts)
