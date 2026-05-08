"""Check MyWebLink.aspx content."""
with open('test_myweblink.html', 'rb') as f:
    content = f.read()
print(content.decode('utf-8', errors='replace'))
