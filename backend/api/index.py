"""
Vercel serverless entry point for OpenCouncil backend.

Vercel experimentalServices sends raw HTTP proxy events to the Lambda.
These are NOT API Gateway events, so Mangum can't auto-detect them.
We build a minimal ASGI-to-WSGI bridge instead.
"""

import asyncio
import io
import sys
import os
from pathlib import Path

# Ensure backend root is on sys.path
_backend_root = Path(__file__).parent.parent
if str(_backend_root) not in sys.path:
    sys.path.insert(0, str(_backend_root))

_handler = None


class _ASGI2WSGI:
    """
    Minimal ASGI-to-WSGI bridge.

    Takes a FastAPI ASGI app and wraps it as a WSGI callable,
    which Vercel Lambda can invoke directly.
    """

    def __init__(self, asgi_app):
        self.asgi_app = asgi_app

    async def _run_app(self, scope, body):
        """Run the ASGI app and collect the response."""
        async def receive():
            if body:
                msg = {"type": "http.request", "body": body, "more_body": False}
                return msg
            return {"type": "http.disconnect"}

        response = {"status": 200, "headers": [], "body": b""}

        async def send(message):
            if message["type"] == "http.response.start":
                response["status"] = message["status"]
                response["headers"] = message.get("headers", [])
            elif message["type"] == "http.response.body":
                response["body"] = response.get("body", b"") + message.get("body", b"")

        await self.asgi_app(scope, receive, send)
        return response

    def __call__(self, env, start_response):
        """WSGI entry point."""
        # Build ASGI scope from WSGI environ
        path = env.get("PATH_INFO", "/")
        qs = env.get("QUERY_STRING", "").encode()
        method = env.get("REQUEST_METHOD", "GET")

        scope = {
            "type": "http",
            "asgi": {"version": "3.0"},
            "http_version": env.get("SERVER_PROTOCOL", "HTTP/1.1").rsplit("/", 1)[-1],
            "method": method,
            "scheme": env.get("wsgi.url_scheme", "http"),
            "path": path,
            "raw_path": path.encode(),
            "query_string": qs,
            "headers": [],
            "client": None,
            "server": None,
        }

        # Build headers list
        headers = scope["headers"]
        for key, value in env.items():
            if key.startswith("HTTP_"):
                h = key[5:].replace("_", "-").lower()
                headers.append((h.encode(), value.encode()))
        ct = env.get("CONTENT_TYPE")
        if ct:
            headers.append(("content-type".encode(), ct.encode()))
        cl = env.get("CONTENT_LENGTH")
        if cl:
            headers.append(("content-length".encode(), cl.encode()))

        # Read body
        body = env.get("wsgi.input", io.BytesIO(b"")).read()

        # Run the ASGI app synchronously
        loop = asyncio.new_event_loop()
        try:
            asyncio.set_event_loop(loop)
            response = loop.run_until_complete(self._run_app(scope, body))
        finally:
            loop.close()

        # Build WSGI response
        status_code = response["status"]
        status_text = "OK" if 200 <= status_code < 300 else "Error"
        status_line = f"{status_code} {status_text}"

        wsgi_headers = []
        for k, v in response["headers"]:
            if isinstance(k, bytes):
                k = k.decode()
            if isinstance(v, bytes):
                v = v.decode()
            wsgi_headers.append((k, v))

        start_response(status_line, wsgi_headers)
        return [response["body"]]


def _get_handler():
    """Import FastAPI app lazily and wrap it as WSGI."""
    global _handler
    if _handler is not None:
        return _handler

    from api.server import app as fastapi_app
    _handler = _ASGI2WSGI(fastapi_app)
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