FROM python:3.12-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements first for better caching
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy the rest of the application
COPY . .

# Set VERCEL flag for SQLite /tmp path
ENV VERCEL=1

# Expose the port Vercel provides
EXPOSE $PORT

# Start the server
CMD uvicorn api.server:app --host 0.0.0.0 --port ${PORT:-8000}
