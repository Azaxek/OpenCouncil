---
title: Civic City Hub Backend
emoji: 🏛️
colorFrom: blue
colorTo: indigo
sdk: docker
pinned: false
app_port: 7860
---

# Civic City Hub Backend

FastAPI backend for Civic City Hub — a platform that fetches, summarizes, and displays city council agendas.

## Environment Variables

Set these in your HF Space settings:

| Variable | Description |
|----------|-------------|
| `DEEPSEEK_API_KEY` | Your DeepSeek API key for LLM summarization |
| `DATABASE_URL` | Supabase PostgreSQL connection string |

## Local Development

```bash
cd backend
pip install -r requirements.txt
python run.py
```

The server starts at `http://localhost:8000`. API docs at `http://localhost:8000/docs`.
