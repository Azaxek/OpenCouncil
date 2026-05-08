"""Check if Laserfiche has a text extraction endpoint."""
import re

with open('test_agenda.pdf', 'rb') as f:
    content = f.read()

html = content.decode('utf-8', errors='replace')

# Look for ViewTextLink or any text-related URLs
# Find all JavaScript
scripts = re.findall(r'<script[^>]*>(.*?)</script>', html, re.IGNORECASE | re.DOTALL)

for i, script in enumerate(scripts):
    if 'text' in script.lower() or 'Text' in script:
        # Find URLs in the script
        urls = re.findall(r'[\"\']([^\"\']*text[^\"\']*)[\"\']', script, re.IGNORECASE)
        if urls:
            print(f"=== Script {i} text URLs ===")
            for u in urls:
                print(f"  {u}")

# Also look for any hidden inputs or divs related to text
text_divs = re.findall(r'<div[^>]*id=[\"\']([^\"\']*text[^\"\']*)[\"\'][^>]*>', html, re.IGNORECASE)
print(f"\n=== Text-related divs ===")
for d in text_divs:
    print(f"  {d}")

# Look for the full HTML structure around the document viewer
# Find the main content area
main_content = re.findall(r'<div[^>]*class=[\"\']DocumentPageToolbar[^>]*>(.*?)</div>', html, re.IGNORECASE | re.DOTALL)
print(f"\n=== Toolbar sections ({len(main_content)}) ===")
for mc in main_content[:2]:
    print(mc[:500])

# Find all links
all_links = re.findall(r'href=[\"\']([^\"\']+)[\"\']', html)
print(f"\n=== All links ===")
for link in all_links:
    if 'text' in link.lower() or 'export' in link.lower() or 'download' in link.lower() or 'print' in link.lower():
        print(f"  {link}")
