# Dockerfile for Hugging Face Spaces deployment
# Uses Python 3.12 slim image

FROM python:3.12-slim

WORKDIR /app

# Install system dependencies (psycopg2 needs libpq)
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements first for layer caching
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy the entire backend directory
COPY . .

# Expose the port HF Spaces will route to
EXPOSE 8000

# Start the FastAPI server
CMD ["uvicorn", "api.server:app", "--host", "0.0.0.0", "--port", "8000"]
