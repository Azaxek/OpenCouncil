"""Check the SQLite database for Three P's fields."""
import sqlite3
import json

conn = sqlite3.connect("data/civic_city_hub.db")
conn.row_factory = sqlite3.Row
cur = conn.cursor()

# Get the summary row
cur.execute("SELECT * FROM minutes_summaries LIMIT 1")
row = cur.fetchone()
if row:
    print("=== big_picture ===")
    print(row["big_picture"])
    
    print("\n=== what_you_can_do ===")
    wyd = json.loads(row["what_you_can_do"]) if row["what_you_can_do"] else []
    print(f"Count: {len(wyd)}")
    for item in wyd:
        print(f"  action: {item.get('action', '?')}")
        print(f"  who: {item.get('who', '?')}")
    
    print("\n=== key_decisions categories ===")
    kd = json.loads(row["key_decisions"]) if row["key_decisions"] else []
    for item in kd:
        print(f"  {item.get('title', '?')} -> {item.get('category', '?')}")
    
    print("\n=== items categories ===")
    items = json.loads(row["items"]) if row["items"] else []
    for item in items:
        print(f"  {item.get('title', '?')} -> {item.get('category', '?')}")
    
    print("\n=== All columns ===")
    print(list(row.keys()))
else:
    print("No summary found")

conn.close()
