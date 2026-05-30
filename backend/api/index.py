"""
Vercel serverless entry point for OpenCouncil backend.

This is the absolute minimal WSGI app required by Vercel Python runtime.
Only imports modules inside the request handler to avoid Lambda startup crashes.
"""

import sys
import os
from pathlib import Path

# Ensure backend root is on sys.path
_backend_root = Path(__file__).parent.parent
if str(_backend_root) not in sys.path:
    sys.path.insert(0, str(_backend_root))

def app(env, start_response):
    """
    Vercel expects a WSGI callable named 'app'.
    Import FastAPI/Mangum LAZILY on first request.
    ANY import errors will crash Lambda on cold start.
    """
    try:
        # Lazy imports - only run when this function is actually invoked
        from mangum import Mangum
        from api.server import app as fastapi_app
        # Create handler on first call
        handler = Mangum(fastapi_app, lifespan="off")
        # Save it to module so subsequent calls reuse it
        globals().setdefault('_handler', handler)
        return handler(env, start_response)
    except ImportError as e:
        # Even this fallback can fail if json import is problematic
        error_body = f"Backend initialization failed: {e}\n".encode()
        start_response('500 Internal Server Error', [
            ('Content-Type', 'text/plain'),
            ('Content-Length', str(len(error_body))),
        ])
        return [error_body]
    except Exception as e:
        # If this except block runs, the backend crashed but not during import
        import traceback
        tb = traceback.format_exc()
        body = f"Backend error:\n{tb}\n".encode()
        start_response('500 Internal Server Error', [
            ('Content-Type', 'text/plain'),
            ('Content-Length', str(len(body))),
        ])
        return [body]