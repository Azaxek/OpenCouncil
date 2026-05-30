"""
Minimal Vercel serverless entry point for OpenCouncil backend.

Use a raw WSGI handler so FastAPI/Mangum imports happen lazily on first request,
avoiding cold-start crashes from missing or incompatible dependencies.
"""

import os
import sys
from pathlib import Path
from typing import Any

# Signal to storage.py that we're on Vercel (use /tmp for SQLite)
os.environ["VERCEL"] = "1"

# Ensure the backend root is on sys.path so all imports resolve
_backend_root = Path(__file__).parent.parent
if str(_backend_root) not in sys.path:
    sys.path.insert(0, str(_backend_root))

# Change working directory to backend root so relative paths work
os.chdir(str(_backend_root))

# Lazy-loaded WSGI handler
_handler: Any = None

def _get_handler():
    """Import FastAPI app and Mangum adapter lazily on first request."""
    global _handler
    if _handler is not None:
        return _handler

    from mangum import Mangum
    from api.server import app as fastapi_app
    _handler = Mangum(fastapi_app, lifespan="off")
    return _handler

# Vercel expects `app` to be a WSGI callable — make it a function
# that lazy-imports on first invocation
def app(environ: dict, start_response) -> list[bytes]:
    handler = _get_handler()
    return handler(environ, start_response)