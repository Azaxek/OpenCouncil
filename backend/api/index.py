"""
Vercel serverless entry point for OpenCouncil backend.

Vercel's experimentalServices sends direct HTTP proxy requests to the Lambda.
Mangum needs explicit handler type for this event format.
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
    Import FastAPI/Mangum lazily on first request.
    """
    try:
        from mangum import Mangum, Handler
        from api.server import app as fastapi_app
        
        # Create handler with explicit HTTP handler type
        handler = Mangum(fastapi_app, lifespan="off")
        # Pre-register the HTTP handler to avoid inference
        handler._handler = Handler.HTTP
        
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