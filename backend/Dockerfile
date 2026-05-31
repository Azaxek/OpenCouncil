# Dockerfile for Hugging Face Spaces deployment
# Uses Python 3.12 slim image

FROM python:3.12-slim

WORKDIR /app

# Install system dependencies (psycopg2 needs libpq, Tesseract OCR needs tesseract-ocr,
# EasyOCR needs libgl1 for OpenCV)
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    libpq-dev \
    tesseract-ocr \
    tesseract-ocr-eng \
    tesseract-ocr-fra \
    libgl1 \
    libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements first for layer caching
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy the entire backend directory
COPY . .

# HF Spaces routes traffic to port 7860 by default
EXPOSE 7860

# Start the FastAPI server on the HF Spaces expected port
CMD ["uvicorn", "api.server:app", "--host", "0.0.0.0", "--port", "7860"]
