"""
Vercel serverless entry point for Civic City Hub backend.

This file is used by Vercel's experimental services to serve the FastAPI app.
It imports the app from server.py and exposes it as a ASGI application.

Vercel Python serverless functions expect a variable named `app` that is
an ASGI or WSGI application.
"""

import sys
import os
from pathlib import Path

# Ensure the backend root is on the path so imports work
_backend_root = Path(__file__).parent.parent
if str(_backend_root) not in sys.path:
    sys.path.insert(0, str(_backend_root))

# Import the FastAPI app from server.py
from api.server import app

# Vercel ASGI expects the app to be named 'app'
# The 'app' variable is already the FastAPI instance from server.py
