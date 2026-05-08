"""Check if the downloaded PDF has extractable text."""
from PyPDF2 import PdfReader
import io

with open('test_agenda.pdf', 'rb') as f:
    content = f.read()

reader = PdfReader(io.BytesIO(content))
print(f"Pages: {len(reader.pages)}")
for i, page in enumerate(reader.pages):
    text = page.extract_text()
    print(f"Page {i+1}: {len(text)} chars")
    if text and text.strip():
        print(f"  Text preview: {text[:200]}")
    else:
        print(f"  [No extractable text - likely scanned image]")
