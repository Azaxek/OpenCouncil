---
title: CivillySimplified Backend
emoji: 🏛️
colorFrom: blue
colorTo: indigo
sdk: docker
pinned: false
app_port: 7860
---

# CivillySimplified

A platform that fetches, summarizes, and displays city council agendas.

## Dockerfile

The Dockerfile is at [`backend/Dockerfile`](backend/Dockerfile).

## Environment Variables

Set these in your HF Space settings:

| Variable | Description |
|----------|-------------|
| `DEEPSEEK_API_KEY` | Your DeepSeek API key for LLM summarization |
| `DATABASE_URL` | Supabase PostgreSQL connection string |
