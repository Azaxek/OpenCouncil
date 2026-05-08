# HF Spaces root Dockerfile — delegates to backend/Dockerfile
FROM python:3.12-slim

WORKDIR /app

# Install system dependencies (psycopg2 needs libpq)
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# Copy backend requirements first for layer caching
COPY backend/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy the entire repo (needed for backend code)
COPY . .

# HF Spaces routes traffic to port 7860 by default
EXPOSE 7860

# Start the FastAPI server
CMD ["uvicorn", "backend.api.server:app", "--host", "0.0.0.0", "--port", "7860"]
