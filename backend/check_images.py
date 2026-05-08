"""Check what images the docview page references."""
import re

with open('test_agenda.pdf', 'rb') as f:
    content = f.read()

html = content.decode('utf-8', errors='replace')

# Find all image references
imgs = re.findall(r'<img[^>]+src=[\"\']([^\"\']+)[\"\']', html, re.IGNORECASE)
print("=== Images ===")
for img in imgs:
    print(f"  {img}")

print()
# Find all background-image URLs
bg = re.findall(r'background[^:]*:\s*url\([\"\']?([^\"\')]+)[\"\']?\)', html, re.IGNORECASE)
print("=== Background images ===")
for b in bg:
    print(f"  {b}")

print()
# Look for the image rendering URL pattern
# Laserfiche typically uses /WebLink/0/doc/ID/PageN.aspx which renders as HTML
# But the actual image might be served differently
# Look for any URL with "image" or "img" or "page" in it
all_urls = re.findall(r'(?:src|href)=[\"\']([^\"\']+)[\"\']', html, re.IGNORECASE)
print("=== URLs with 'image' or 'page' or 'doc' ===")
for u in all_urls:
    if any(x in u.lower() for x in ['image', 'page', 'doc', 'img', 'getimage', 'render']):
        print(f"  {u}")

print()
# Check for the document viewer JavaScript
scripts = re.findall(r'<script[^>]*>([^<]+)</script>', html, re.IGNORECASE | re.DOTALL)
print(f"=== Scripts ({len(scripts)}) ===")
for i, script in enumerate(scripts):
    if any(x in script.lower() for x in ['image', 'page', 'doc', 'getimage', 'render', 'tiff', 'pdf']):
        print(f"  Script {i}: {script[:300]}")
