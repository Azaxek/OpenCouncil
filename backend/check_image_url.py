"""Find the image rendering URL pattern in the docview page."""
import re

with open('test_agenda.pdf', 'rb') as f:
    content = f.read()

html = content.decode('utf-8', errors='replace')

# Look for the full script that initializes the image display
# The key is TheImageDisplay - find its initialization
scripts = re.findall(r'<script[^>]*>(.*?)</script>', html, re.IGNORECASE | re.DOTALL)

for i, script in enumerate(scripts):
    if 'ImageDisplay' in script or 'imageUrl' in script.lower() or 'pageImage' in script.lower():
        print(f"=== Script {i} ===")
        print(script[:3000])
        print("...")
