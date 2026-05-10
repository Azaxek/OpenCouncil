"""
Seed the HF Space PostgreSQL database with pre-computed OCR data.

Reads from the local SQLite database and pushes to the HF Space
via the /api/minutes/seed endpoint.

Usage:
    python seed_hf_space.py
"""
import json
import sqlite3
import urllib.request
import urllib.error
from pathlib import Path

HF_SPACE_URL = "https://Comfoa-Civilly-Simplified-Backend.hf.space"
DB_PATH = Path(__file__).parent / "data" / "civic_city_hub.db"


def main():
    if not DB_PATH.exists():
        print(f"ERROR: Database not found at {DB_PATH}")
        print("Run precompute_ocr.py first to generate the database.")
        return

    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row

    # Read minutes
    minutes_rows = conn.execute(
        "SELECT id, city, state, meeting_date, meeting_type, title, url, "
        "document_url, raw_text, source FROM minutes"
    ).fetchall()

    if not minutes_rows:
        print("ERROR: No minutes found in database.")
        return

    # Read summaries
    summary_rows = conn.execute(
        "SELECT minutes_id, summary, key_decisions, budget_items, "
        "public_comment_opportunities, items FROM minutes_summaries"
    ).fetchall()
    summaries = {r["minutes_id"]: r for r in summary_rows}

    for m in minutes_rows:
        minutes_id = m["id"]
        print(f"\nSeeding minutes: {m['title']} (ID: {minutes_id})")

        # Build the seed payload
        payload = {
            "minutes_id": minutes_id,
            "title": m["title"],
            "meeting_date": m["meeting_date"],
            "meeting_type": m["meeting_type"],
            "url": m["url"],
            "document_url": m["document_url"],
            "raw_text": m["raw_text"],
            "page_image_urls": [],
            "city": m["city"],
            "state": m["state"],
            "source": m["source"],
        }

        # Add summary if available
        if minutes_id in summaries:
            s = summaries[minutes_id]
            payload["summary_text"] = s["summary"] or ""
            payload["key_decisions"] = json.loads(s["key_decisions"]) if s["key_decisions"] else []
            payload["budget_items"] = json.loads(s["budget_items"]) if s["budget_items"] else []
            payload["public_comment_opportunities"] = (
                json.loads(s["public_comment_opportunities"]) if s["public_comment_opportunities"] else []
            )
            payload["items"] = json.loads(s["items"]) if s["items"] else []
            print(f"  Summary: {s['summary'][:100]}...")
            print(f"  Key decisions: {len(payload['key_decisions'])}")
            print(f"  Items: {len(payload['items'])}")
        else:
            print("  No summary available")

        # Send to HF Space
        url = f"{HF_SPACE_URL}/api/minutes/seed"
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            url,
            data=data,
            headers={"Content-Type": "application/json"},
            method="POST",
        )

        try:
            resp = urllib.request.urlopen(req, timeout=30)
            result = json.loads(resp.read())
            print(f"  Result: {json.dumps(result, indent=2)}")
        except urllib.error.HTTPError as e:
            print(f"  HTTP Error {e.code}: {e.read().decode()[:200]}")
        except Exception as e:
            print(f"  Error: {e}")

    conn.close()
    print("\nDone!")


if __name__ == "__main__":
    main()
