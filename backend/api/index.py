"""
Minimal Vercel serverless entry point for OpenCouncil backend.

Uses Mangum to wrap FastAPI. If imports fail, returns a JSON error response.
"""

import json
import os
import sys
from pathlib import Path

# Signal to storage.py that we're on Vercel (use /tmp for SQLite)
os.environ["VERCEL"] = "1"

# Ensure the backend root is on sys.path
_backend_root = Path(__file__).parent.parent
if str(_backend_root) not in sys.path:
    sys.path.insert(0, str(_backend_root))

# Change working directory to backend root
os.chdir(str(_backend_root))

_app = None

def _get_app():
    global _app
    if _app is not None:
        return _app

    try:
        from mangum import Mangum
        from api.server import app as fastapi_app
        _app = Mangum(fastapi_app, lifespan="off")
        return _app
    except Exception as e:
        import traceback
        # Return a simple WSGI app that shows the error
        error_msg = json.dumps({
            "error": f"Backend initialization failed: {str(e)}",
            "traceback": traceback.format_exc(),
        })
        def error_app(environ, start_response):
            start_response("500 Internal Server Error", [
                ("Content-Type", "application/json"),
                ("Content-Length", str(len(error_msg))),
            ])
            return [error_msg.encode()]
        _app = error_app
        return _app

def app(environ, start_response):
    handler = _get_app()
    return handler(environ, start_response)