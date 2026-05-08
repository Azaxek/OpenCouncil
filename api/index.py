"""
Vercel serverless entry point for Civic City Hub backend.

Vercel Python serverless functions use WSGI. FastAPI is ASGI, so we use
Mangum — an ASGI-to-WSGI adapter — to bridge the gap.

Vercel looks for `app` (WSGI callable) in api/index.py at the project root.
"""
import os
import sys
import traceback
from pathlib import Path

# Signal to storage.py that we're on Vercel (use /tmp for SQLite)
os.environ["VERCEL"] = "1"

# Ensure the backend root is on sys.path so all imports resolve
_backend_root = Path(__file__).parent / "backend"
if str(_backend_root) not in sys.path:
    sys.path.insert(0, str(_backend_root))

# Change working directory to backend root so relative paths work
os.chdir(str(_backend_root))

try:
    # Import the FastAPI app
    from api.server import app as fastapi_app

    # Wrap with Mangum for Vercel WSGI compatibility
    from mangum import Mangum

    # Vercel Python runtime looks for 'app' (WSGI callable)
    app = Mangum(fastapi_app, lifespan="off")
except Exception as e:
    # If anything fails during import, create a fallback app that returns the error
    traceback.print_exc()
    from mangum import Mangum
    from fastapi import FastAPI, Request, Response

    fallback_app = FastAPI()

    @fallback_app.api_route("/{path:path}", methods=["GET", "POST", "PUT", "DELETE", "OPTIONS", "HEAD", "PATCH"])
    async def error_handler(request: Request, path: str):
        return Response(
            content=f"Import Error: {str(e)}\n\n{traceback.format_exc()}",
            status_code=500,
            media_type="text/plain",
        )

    app = Mangum(fallback_app, lifespan="off")
