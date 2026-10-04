---
title: OpenCouncil Backend
emoji: 🏛️
colorFrom: blue
colorTo: indigo
sdk: docker
pinned: false
app_port: 7860
---

# OpenCouncil

**City council meetings, explained in plain English.**

Council agendas and minutes are long PDFs buried on city websites. OpenCouncil fetches them automatically, uses AI to summarize them, and shows the results in a clean, searchable site, so residents can see what their city is deciding without reading 80 pages.

**Live site:** [open-council-alpha.vercel.app](https://open-council-alpha.vercel.app)

## What it does

- **Collects documents** from each city's own system (Laserfiche, OnBase, CivicPlus, or plain PDF pages) and refreshes them on a schedule.
- **Reads scanned PDFs** with a three-step fallback: embedded text first, then free OCR services (OCR.space, then Hugging Face TrOCR and Nougat).
- **Summarizes** each meeting with an LLM (Llama 3.1 via Groq) into short, readable highlights.
- **Detects your city** from your location and lists that city's meetings.
- **Verifies sources** so every summary links back to the original document.
- **Shares** summaries as generated social-media cards.

Currently supported cities: **Paris, TX**, **Sulphur Springs, TX**, **Frisco, TX**. Adding one is a new entry in [`backend/data/cities.json`](backend/data/cities.json) plus, if needed, a connector.

## How it's built

```
Next.js frontend (Vercel)  ──/api proxy──>  FastAPI backend (Python)  ──>  PostgreSQL (Supabase)
                                                  │
                         city connectors ─────────┤  fetch agendas/minutes
                         OCR + LLM summarizer ────┤  turn PDFs into summaries
                         social card generator ───┘  shareable images
```

| Part | Folder | Notes |
|---|---|---|
| Frontend | [`frontend/`](frontend) | Next.js 16, React, TypeScript. Pages for browsing minutes and verifying sources. |
| Backend API | [`backend/api/`](backend/api) | FastAPI. Endpoints for cities, minutes, summarizing, and a cron scrape-all (every 2 hours). |
| Connectors | [`backend/connectors/`](backend/connectors) | One module per document system. |
| Summarizer | [`backend/parsers/`](backend/parsers) | OCR pipeline and LLM summarization. |
| Social cards | [`backend/social/`](backend/social) | Card image generation and posting. |

## Run it locally

```bash
# backend
cd backend
pip install -r requirements.txt
cp .env.example .env      # add your keys
python run.py             # http://localhost:7860

# frontend (new terminal)
cd frontend
npm install
npm run dev               # http://localhost:3000
```

Environment variables (see [`backend/.env.example`](backend/.env.example)): an LLM API key for summaries and a PostgreSQL `DATABASE_URL`.

## Deploy

[`SETUP.md`](SETUP.md) walks through the free setup: Supabase for the database, Groq for the AI key, and Vercel for hosting. The backend also ships with a [`Dockerfile`](backend/Dockerfile) for Hugging Face Spaces.

## Tech stack

Next.js, React, TypeScript, Python, FastAPI, PostgreSQL (Supabase), Groq (Llama 3.1), OCR.space, Hugging Face, Docker, Vercel
