"""Extract the full script that contains text retrieval."""
import re

with open('test_agenda.pdf', 'rb') as f:
    content = f.read()

html = content.decode('utf-8', errors='replace')

scripts = re.findall(r'<script[^>]*>(.*?)</script>', html, re.IGNORECASE | re.DOTALL)

# Find the script with STR_TEXT_RETRIEVAL_FAILED
for i, script in enumerate(scripts):
    if 'STR_TEXT_RETRIEVAL_FAILED' in script:
        print(f"=== Script {i} (length={len(script)}) ===")
        # Decode unicode escapes
        decoded = script.encode().decode('unicode_escape', errors='replace')
        print(decoded[:5000])
        break
