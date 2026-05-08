"""
Vercel serverless entry point for Civic City Hub backend.

Vercel Python serverless functions use WSGI. FastAPI is ASGI, so we use
Mangum — an ASGI-to-WSGI adapter — to bridge the gap.

Key points:
- Mangum wraps the FastAPI ASGI app into a WSGI callable
- Vercel looks for `app` (WSGI) or `handler` (WSGI) in api/index.py
- We set the VERCEL=1 env var so storage.py uses /tmp for SQLite
"""

import os
import sys
from pathlib import Path

# Signal to storage.py that we're on Vercel (use /tmp for SQLite)
os.environ["VERCEL"] = "1"

# Ensure the backend root is on sys.path so all imports resolve
_backend_root = Path(__file__).parent.parent
if str(_backend_root) not in sys.path:
    sys.path.insert(0, str(_backend_root))

# Change working directory to backend root so relative paths work
os.chdir(str(_backend_root))

# Import the FastAPI app
from api.server import app as fastapi_app

# Wrap with Mangum for Vercel WSGI compatibility
from mangum import Mangum

# Vercel Python runtime looks for 'app' (WSGI callable)
app = Mangum(fastapi_app, lifespan="off")
