#!/bin/bash
# Start script for Vercel experimental services (Python)
# Vercel runs this after the build step to start the service

# Set VERCEL flag so storage.py uses /tmp for SQLite
export VERCEL=1

# Start the FastAPI server with uvicorn
# $PORT is set by Vercel
uvicorn api.server:app --host 0.0.0.0 --port ${PORT:-8000}
