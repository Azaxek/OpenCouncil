"""Check what docview.aspx actually returns."""
import re

with open('test_agenda.pdf', 'rb') as f:
    content = f.read()

html = content.decode('utf-8', errors='replace')

print(f"File size: {len(content)} bytes")
print(f"First 100 chars: {html[:100]}")
print()

# Find all hrefs
urls = re.findall(r'href=[\"\']([^\"\']+)[\"\']', html)
print("=== All hrefs ===")
for u in urls:
    print(f"  {u}")

print()
# Find all src attributes
srcs = re.findall(r'src=[\"\']([^\"\']+)[\"\']', html)
print("=== All src ===")
for s in srcs:
    print(f"  {s}")

print()
# Check for iframes
iframes = re.findall(r'<iframe[^>]*>', html, re.IGNORECASE)
print(f"=== Iframes ({len(iframes)}) ===")
for ifr in iframes:
    print(f"  {ifr}")

print()
# Check for embed/object tags
embeds = re.findall(r'<(?:embed|object)[^>]*>', html, re.IGNORECASE)
print(f"=== Embed/Object tags ({len(embeds)}) ===")
for e in embeds:
    print(f"  {e}")

print()
# Look for the word "pdf" in the HTML
lines = html.split('\n')
print(f"=== Lines containing 'pdf' (case insensitive) ===")
for i, line in enumerate(lines):
    if 'pdf' in line.lower():
        print(f"  Line {i}: {line.strip()[:200]}")
