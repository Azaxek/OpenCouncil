"""
Pre-compute OCR text and DeepSeek summary for the latest Paris city council minutes,
then save to the local SQLite database.

This allows the Hugging Face Space to serve pre-computed results without needing
to reach documents.paristexas.gov from within the HF network.
"""
import asyncio
import io
import os
import sys
from pathlib import Path

# Add backend dir to path
sys.path.insert(0, str(Path(__file__).parent))

# CRITICAL: Prevent storage.py from using PostgreSQL.
# We want local SQLite. storage.py's .env loader checks `if key not in os.environ`,
# so we set DATABASE_URL to empty string to block it from being loaded from .env.
os.environ["DATABASE_URL"] = ""

# Now load .env for other settings (DEEPSEEK_API_KEY, etc.)
_env_file = Path(__file__).parent / ".env"
if _env_file.exists():
    with open(_env_file) as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, _, val = line.partition("=")
                key = key.strip()
                val = val.strip().strip("\"'")
                if key not in os.environ:
                    os.environ[key] = val

from connectors.laserfiche import LaserficheConnector
from parsers.llm_summarizer import LLMSummarizer
from storage import save_minutes, save_minutes_summary, reset_database, init_db
from PIL import Image


async def main():
    print("=" * 70)
    print("PRE-COMPUTING OCR + SUMMARY FOR PARIS CITY COUNCIL MINUTES")
    print("=" * 70)

    connector = LaserficheConnector()
    summarizer = LLMSummarizer()

    try:
        # Step 1: Get the latest minutes
        print("\n[STEP 1] Fetching latest minutes from Laserfiche...")
        minutes = await connector.get_latest_minutes()
        print(f"  Title: {minutes.title}")
        print(f"  Date: {minutes.meeting_date}")
        print(f"  Document URL: {minutes.document_url}")
        print(f"  Page image URLs: {len(minutes.page_image_urls)}")

        if not minutes.page_image_urls:
            print("  No page image URLs found!")
            return

        # Step 2: Fetch actual page images
        print("\n[STEP 2] Fetching page images...")
        images = await connector.fetch_page_images(
            minutes.document_url, page_urls=minutes.page_image_urls
        )
        print(f"  Fetched {len(images)} page images")

        if not images:
            print("  No images fetched!")
            return

        # Step 3: Run OCR on ALL pages
        print("\n[STEP 3] Running OCR on all pages...")
        all_text = ""
        for i, img_bytes in enumerate(images):
            best_text = ""
            best_engine = "none"

            # EasyOCR
            try:
                text_easy = summarizer._ocr_with_easyocr(img_bytes)
                if text_easy and len(text_easy.strip()) > len(best_text.strip()):
                    best_text = text_easy.strip()
                    best_engine = "EasyOCR"
            except Exception as e:
                print(f"    EasyOCR page {i+1} failed: {e}")

            # Tesseract — try multiple PSM modes and pick best
            try:
                img = Image.open(io.BytesIO(img_bytes))
                processed = summarizer._preprocess_image_for_ocr(img, for_easyocr=False)

                tess_psm_modes = [6, 4, 3, 1]
                tess_results = []
                for psm in tess_psm_modes:
                    try:
                        text = summarizer._pytesseract.image_to_string(
                            processed,
                            lang=summarizer.TESSERACT_LANGUAGES,
                            config=f"--psm {psm} --oem 3",
                        ).strip()
                        if text:
                            tess_results.append((text, psm))
                    except Exception:
                        continue

                # Also try raw (unprocessed) image with PSM 6
                try:
                    text_raw = summarizer._pytesseract.image_to_string(
                        img,
                        lang=summarizer.TESSERACT_LANGUAGES,
                        config="--psm 6 --oem 3",
                    ).strip()
                    if text_raw:
                        tess_results.append((text_raw, 0))  # 0 = raw
                except Exception:
                    pass

                # Pick best: prefer longer text with good alpha ratio
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
            except Exception as e:
                print(f"    Tesseract page {i+1} failed: {e}")

            if best_text:
                all_text += f"\n\n--- Page {i+1} ({best_engine}) ---\n{best_text}"
                print(f"  Page {i+1}: {best_engine} - {len(best_text)} chars")
            else:
                print(f"  Page {i+1}: NO TEXT EXTRACTED")

        print(f"\n  TOTAL EXTRACTED TEXT: {len(all_text)} chars")

        if not all_text.strip():
            print("  No text extracted by any OCR engine!")
            return

        # Step 4: Save OCR text to minutes
        print("\n[STEP 4] Saving OCR text to minutes...")
        minutes.raw_text = all_text

        # Step 5: Run DeepSeek summarization
        print("\n[STEP 5] Running DeepSeek summarization...")
        # Call _summarize_with_text directly since we already have OCR text
        summary = await summarizer._summarize_with_text(minutes)
        print(f"\n  Summary: {summary.summary[:500]}")
        print(f"  Key decisions: {len(summary.key_decisions)}")
        print(f"  Budget items: {len(summary.budget_items)}")
        print(f"  Items: {len(summary.items)}")

        # Step 6: Save to database
        print("\n[STEP 6] Saving to local SQLite database...")
        # Initialize database schema first (creates tables if they don't exist)
        init_db()
        print("  Database schema initialized")
        # Reset to clear any stale data
        reset_database()
        print("  Database reset complete")

        # Save minutes
        save_minutes(minutes)
        print(f"  Minutes saved (ID: {minutes.id})")

        # Save summary
        save_minutes_summary(minutes.id, summary)
        print(f"  Summary saved for minutes {minutes.id}")

        # Verify
        from storage import get_minutes, get_minutes_summary
        saved_minutes = get_minutes(minutes.id)
        saved_summary = get_minutes_summary(minutes.id)
        if saved_minutes and saved_summary:
            print(f"\n  VERIFICATION: Minutes and summary retrieved successfully!")
            print(f"  Summary text: {saved_summary.summary[:200]}...")
        else:
            print(f"\n  VERIFICATION FAILED!")

        print(f"\n{'=' * 70}")
        print(f"DONE! Database saved to: {Path(__file__).parent / 'data' / 'civic_city_hub.db'}")
        print(f"Push this file to HF Spaces to serve pre-computed results.")
        print(f"{'=' * 70}")

    finally:
        await connector.close()
        await summarizer.close()


if __name__ == "__main__":
    asyncio.run(main())
