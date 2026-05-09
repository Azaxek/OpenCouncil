"""
Run the Civic City Hub API server.

Usage:
    python run.py              # Start server on default port 8000
    python run.py --port 8080  # Start server on custom port
"""

import os
import sys
import uvicorn
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

if __name__ == "__main__":
    port = int(sys.argv[sys.argv.index("--port") + 1]) if "--port" in sys.argv else 8000

    providers = []
    if os.getenv("DEEPSEEK_API_KEY"):
        providers.append("DeepSeek (text + OCR)")
    llm_status = ", ".join(providers) if providers else "Not configured"

    ocr_available = False
    try:
        import pytesseract
        import PIL
        ocr_available = True
    except ImportError:
        pass

    print("=" * 60)
    print("  Civic City Hub API Server")
    print("=" * 60)
    print(f"  Port:     {port}")
    print(f"  City:     Paris, TX")
    print(f"  Website:  https://www.paristexas.gov")
    print(f"  LLM:      {llm_status}")
    print(f"  OCR:      {'Tesseract (free)' if ocr_available else 'Not installed (pip install pytesseract Pillow)'}")
    print()
    print("  Endpoints:")
    print(f"    Health:     http://localhost:{port}/health")
    print(f"    Minutes:    http://localhost:{port}/api/minutes")
    print(f"    Summarize:  http://localhost:{port}/api/minutes/summarize")
    print(f"    Docs:       http://localhost:{port}/docs")
    print("=" * 60)

    uvicorn.run(
        "api.server:app",
        host="0.0.0.0",
        port=port,
        reload=True,
    )
