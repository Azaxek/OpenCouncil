# OpenCouncil — Vercel Deployment Setup

## 1. Create a Supabase Project (Free)

1. Go to [supabase.com](https://supabase.com) and sign up
2. Create a new project
3. From your project dashboard → Settings → Database:
   - Copy the **Connection string** (URI format)
   - It looks like: `postgresql://postgres:xxxxx@db.xxxxx.supabase.co:5432/postgres`

## 2. Get a Groq API Key (Free, 14,400 req/day)

1. Go to [console.groq.com/keys](https://console.groq.com/keys)
2. Create an API key
3. The key starts with `gsk_`

## 3. Deploy to Vercel

1. Import `github.com/Azaxek/OpenCouncil`
2. Set **Root Directory** to `frontend` (Settings > General). The Next.js app lives there.
3. Set `NEXT_PUBLIC_API_URL` to your backend's address (the FastAPI backend in `backend/` runs separately, for example as a Hugging Face Space using `backend/Dockerfile`). Leave it unset to use the default Space.

The backend needs these environment variables:

| Variable | Value | Required? |
|----------|-------|-----------|
| `GROK_API_KEY` | Your Groq API key (`gsk_...`) | Required for AI summaries |
| `DATABASE_URL` | Supabase connection string (`postgresql://...`) | Required for persistence |

## 4. Deploy

Click **Deploy**. The frontend serves at `your-project.vercel.app` and proxies `/api/*` to the backend through a Next.js route. The `/samples` pages are static and work even if the backend is down.

## 5. Verify

- `https://your-project.vercel.app/health` — should show `{"status":"ok"}`
- `https://your-project.vercel.app/api/cities` — should list 3 cities
- `https://your-project.vercel.app/` — frontend home page

## 6. Optional: Vercel Cron Jobs

The backend no longer includes APScheduler (it crashed your computer).  
To scrape minutes automatically, add a Vercel Cron Job:

1. Go to Vercel Dashboard → your project → Cron Jobs
2. Add a job that hits `https://your-project.vercel.app/api/minutes/fetch-latest`
3. Every 6 hours or daily

## Minimum Viable Setup

```
GROK_API_KEY=gsk_your_groq_key_here
DATABASE_URL=postgresql://postgres:password@db.xxxxx.supabase.co:5432/postgres
VERCEL=1
```

**That's it** — 3 environment variables and you're live.