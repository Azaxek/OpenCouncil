"""
Vercel serverless entry point for OpenCouncil backend.

Lazy-imports everything on first request. Runs initialization once.
"""

import sys
import os
from pathlib import Path

# Ensure backend root is on sys.path
_backend_root = Path(__file__).parent.parent
if str(_backend_root) not in sys.path:
    sys.path.insert(0, str(_backend_root))

_handler = None
_initialized = False

def _get_handler():
    """Import FastAPI app lazily and wrap it as WSGI."""
    global _handler
    if _handler is not None:
        return _handler

    from api.server import app as fastapi_app
    from mangum import Mangum
    # Use lifespan="auto" so FastAPI runs its lifespan (init_db, connectors, etc.)
    _handler = Mangum(fastapi_app, lifespan="auto")
    return _handler


def app(env, start_response):
    """
    Vercel expects a WSGI callable named 'app'.
    """
    try:
        handler = _get_handler()
        return handler(env, start_response)

    except ImportError as e:
        error_body = f"Backend initialization failed: {e}\n".encode()
        start_response('500 Internal Server Error', [
            ('Content-Type', 'text/plain'),
            ('Content-Length', str(len(error_body))),
        ])
        return [error_body]
    except Exception as e:
        import traceback
        tb = traceback.format_exc()
        body = f"Backend error:\n{tb}\n".encode()
        start_response('500 Internal Server Error', [
            ('Content-Type', 'text/plain'),
            ('Content-Length', str(len(body))),
        ])
        return [body]
