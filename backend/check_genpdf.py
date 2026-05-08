"""Check what GeneratePDF.aspx returned."""
with open('test_generated.pdf', 'rb') as f:
    c = f.read()
print(f"Size: {len(c)} bytes")
print(f"Content: {c[:500]}")
