"""Verify the HF Space API returns Three P's fields."""
import urllib.request
import json

url = "https://Comfoa-Civilly-Simplified-Backend.hf.space/api/minutes/343be0dd"
resp = urllib.request.urlopen(url, timeout=15)
data = json.loads(resp.read())

print("=== Top-level keys ===")
print(list(data.keys()))
print()

summary = data.get("summary")
print(f"summary type: {type(summary).__name__}")
if isinstance(summary, dict):
    print("summary keys:", list(summary.keys()))
    print()
    print("=== big_picture ===")
    print(repr(summary.get("big_picture", "MISSING")))
    print()
    print("=== what_you_can_do ===")
    wyd = summary.get("what_you_can_do", [])
    print(f"Count: {len(wyd)}")
    for item in wyd:
        print(f"  action: {item.get('action', '?')}")
        print(f"  who: {item.get('who', '?')}")
elif isinstance(summary, str):
    print(f"summary (str): {summary[:200]}")
else:
    print(f"summary value: {summary}")
