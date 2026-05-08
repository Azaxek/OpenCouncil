"""Extract the full JavaScript from docview.aspx to understand image rendering."""
import re

with open('test_agenda.pdf', 'rb') as f:
    content = f.read()

html = content.decode('utf-8', errors='replace')

# Extract all script content
scripts = re.findall(r'<script[^>]*>(.*?)</script>', html, re.IGNORECASE | re.DOTALL)
print(f"=== Total scripts: {len(scripts)} ===")
for i, script in enumerate(scripts):
    s = script.strip()
    if len(s) > 10:
        print(f"\n--- Script {i} (length={len(s)}) ---")
        print(s[:2000])

# Also look for the document viewer div structure
print("\n\n=== Document viewer divs ===")
doc_divs = re.findall(r'<div[^>]*id=[\"\']([^\"\']*(?:Doc|Page|Image|Text|View)[^\"\']*)[\"\'][^>]*>', html, re.IGNORECASE)
for d in doc_divs:
    print(f"  {d}")

# Look for the image rendering URL
print("\n\n=== Looking for image source patterns ===")
# Laserfiche often uses WebResource.axd or a specific image handler
all_src = re.findall(r'src=[\"\']([^\"\']+)[\"\']', html)
for s in all_src:
    if 'resource' in s.lower() or 'image' in s.lower() or 'handler' in s.lower() or 'ashx' in s.lower() or 'aspx' in s.lower():
        print(f"  {s}")
