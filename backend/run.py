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

    llm_status = "Available (DeepSeek)" if os.getenv("DEEPSEEK_API_KEY") else "Not configured"

    print("=" * 60)
    print("  Civic City Hub API Server")
    print("=" * 60)
    print(f"  Port:     {port}")
    print(f"  City:     Paris, TX")
    print(f"  Website:  https://www.paristexas.gov")
    print(f"  LLM:      {llm_status}")
    print()
    print("  Endpoints:")
    print(f"    Health:     http://localhost:{port}/health")
    print(f"    Agendas:    http://localhost:{port}/api/agendas")
    print(f"    Summarize:  http://localhost:{port}/api/summarize")
    print(f"    Docs:       http://localhost:{port}/docs")
    print("=" * 60)

    uvicorn.run(
        "api.server:app",
        host="0.0.0.0",
        port=port,
        reload=True,
    )
