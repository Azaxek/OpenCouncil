"use client";

import Link from "next/link";
import { useEffect, useState } from "react";

interface HealthResponse {
  status: string;
  city: string;
  llm_available: boolean;
  llm_provider: string;
  storage: string;
}

interface MinutesListItem {
  id: string;
  title: string;
  meeting_date: string | null;
  meeting_type?: string;
  url: string;
  document_url: string | null;
  has_summary?: boolean;
  city?: string;
  state?: string;
}

interface CityInfo {
  id: string;
  name: string;
  state: string;
  full_name?: string;
}

// API base URL — in production points to the HF Space backend.
// Local dev: Next.js rewrites proxy /api/* to localhost:8000
// On Vercel: set NEXT_PUBLIC_API_URL env var to the HF Space URL
const API_BASE = typeof window !== "undefined"
  ? (window as any).__NEXT_PUBLIC_API_URL || ""
  : "";

export default function HomePage() {
  const [health, setHealth] = useState<HealthResponse | null>(null);
  const [minutesList, setMinutesList] = useState<MinutesListItem[]>([]);
  const [cityInfo, setCityInfo] = useState<CityInfo | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    Promise.all([
      fetch(`${API_BASE}/health`).then((res) => res.json()).catch(() => null),
      fetch(`${API_BASE}/api/detect-city`).then((res) => res.json()).catch(() => null),
      fetch(`${API_BASE}/api/minutes?limit=5`).then((res) => res.json()).catch(() => ({ minutes: [] })),
    ])
      .then(([healthData, cityData, minutesData]) => {
        setHealth(healthData);
        if (cityData) setCityInfo(cityData.city);
        setMinutesList(minutesData.minutes || []);
        setLoading(false);
      })
      .catch(() => setLoading(false));
  }, []);

  const formatDate = (dateStr: string | null) => {
    if (!dateStr) return "";
    try {
      return new Date(dateStr).toLocaleDateString("en-US", {
        month: "long", day: "numeric", year: "numeric",
      });
    } catch { return dateStr; }
  };

  const cityName = cityInfo?.full_name || (cityInfo ? `${cityInfo.name}, ${cityInfo.state}` : "Paris, Texas");
  const latestMinutes = minutesList[0];
  const otherMinutes = minutesList.slice(1, 4);

  return (
    <div className="space-y-8">
      <section>
        {loading ? (
          <div className="space-y-4">
            <div className="skeleton h-8 w-1/3" />
            <div className="skeleton h-64 w-full" />
          </div>
        ) : latestMinutes ? (
          <Link href={`/minutes/${latestMinutes.id}`} style={{ textDecoration: "none" }}>
            <article className="article-card article-card-featured" style={{ padding: "2rem" }}>
              <div style={{ display: "flex", flexDirection: "column", gap: "1rem" }}>
                <div style={{ display: "flex", alignItems: "center", gap: "0.75rem" }}>
                  <span className="news-section-tag">Featured Minutes</span>
                  {latestMinutes.has_summary && <span className="badge badge-brand">AI Summary Available</span>}
                </div>
                <h2 className="news-headline-xl">{latestMinutes.title}</h2>
                <div className="news-byline">
                  {cityName} — {formatDate(latestMinutes.meeting_date)}
                  {latestMinutes.meeting_type && ` — ${latestMinutes.meeting_type}`}
                </div>
                <p className="news-body" style={{ marginTop: "0.5rem" }}>
                  {latestMinutes.has_summary
                    ? "An AI-powered plain-language summary is available for these minutes. Read the key decisions, budget items, and public comment opportunities."
                    : "View the full meeting minutes with AI-powered plain-language summaries."}
                </p>
                <div><span className="btn btn-primary">Read Full Coverage →</span></div>
              </div>
            </article>
          </Link>
        ) : (
          <article className="article-card" style={{ padding: "2rem", textAlign: "center" }}>
            <h2 className="news-headline-lg" style={{ marginBottom: "0.75rem" }}>Welcome to OpenCouncil</h2>
            <p className="news-body">
              We're currently fetching the latest minutes from {cityName}.
              Check back soon for plain-language summaries of city council meetings.
            </p>
          </article>
        )}
      </section>

      <div className="news-layout">
        <div className="space-y-6">
          <div className="section-header"><span className="news-section-tag">Latest Minutes</span></div>
          {loading ? (
            <div className="space-y-4">
              {[1, 2, 3].map((i) => <div key={i} className="skeleton h-24 w-full" />)}
            </div>
          ) : otherMinutes.length > 0 ? (
            <div className="space-y-4">
              {otherMinutes.map((minutes) => (
                <Link key={minutes.id} href={`/minutes/${minutes.id}`} style={{ textDecoration: "none" }}>
                  <article className="article-card" style={{ padding: "1.25rem" }}>
                    <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", gap: "1rem" }}>
                      <div style={{ flex: 1, minWidth: 0 }}>
                        <h3 className="news-headline-md" style={{ marginBottom: "0.25rem" }}>{minutes.title}</h3>
                        <p className="news-byline">
                          {formatDate(minutes.meeting_date)}{minutes.meeting_type && ` — ${minutes.meeting_type}`}
                        </p>
                      </div>
                      <div style={{ display: "flex", alignItems: "center", gap: "0.5rem", flexShrink: 0 }}>
                        {minutes.has_summary && <span className="badge badge-brand">AI</span>}
                        <span style={{ color: "var(--foreground-secondary)", fontSize: "0.875rem" }}>→</span>
                      </div>
                    </div>
                  </article>
                </Link>
              ))}
            </div>
          ) : (
            <div className="article-card" style={{ padding: "2rem", textAlign: "center" }}>
              <p className="news-body" style={{ marginBottom: "1rem" }}>No minutes available yet.</p>
              <Link href="/minutes" className="btn btn-primary">Browse Minutes</Link>
            </div>
          )}
          {minutesList.length > 0 && (
            <div style={{ textAlign: "center" }}>
              <Link href="/minutes" className="btn btn-secondary">View All Minutes →</Link>
            </div>
          )}
        </div>

        <aside className="space-y-6">
          <div className="sidebar-card">
            <h3>Your City</h3>
            <p className="news-headline-md" style={{ marginBottom: "0.25rem" }}>{cityName}</p>
            <p className="news-byline" style={{ textTransform: "none", letterSpacing: "normal" }}>
              {health ? `API: ${health.status === "ok" ? "Connected" : "Offline"}` : "Connecting..."}
            </p>
            {health && (
              <div style={{ marginTop: "0.75rem", display: "flex", flexDirection: "column", gap: "0.375rem" }}>
                <div style={{ display: "flex", justifyContent: "space-between", fontSize: "0.75rem" }}>
                  <span style={{ color: "var(--foreground-secondary)" }}>AI Summaries</span>
                  <span style={{ color: health.llm_available ? "var(--accent-green)" : "var(--accent-red)" }}>
                    {health.llm_available ? "Active" : "Off"}
                  </span>
                </div>
                <div style={{ display: "flex", justifyContent: "space-between", fontSize: "0.75rem" }}>
                  <span style={{ color: "var(--foreground-secondary)" }}>Provider</span>
                  <span>{health.llm_provider || "—"}</span>
                </div>
                <div style={{ display: "flex", justifyContent: "space-between", fontSize: "0.75rem" }}>
                  <span style={{ color: "var(--foreground-secondary)" }}>Storage</span>
                  <span>{health.storage || "—"}</span>
                </div>
              </div>
            )}
          </div>

          <div className="sidebar-card">
            <h3>How It Works</h3>
            <div style={{ display: "flex", flexDirection: "column", gap: "0.75rem" }}>
              {[
                { step: "1", text: "City publishes meeting minutes on their website" },
                { step: "2", text: "We fetch and parse the document automatically" },
                { step: "3", text: "AI translates legalese into plain English" },
                { step: "4", text: "You stay informed about your local government" },
              ].map((item) => (
                <div key={item.step} style={{ display: "flex", gap: "0.625rem", alignItems: "flex-start" }}>
                  <span className="badge badge-brand" style={{ minWidth: "1.5rem", textAlign: "center" }}>{item.step}</span>
                  <span style={{ fontSize: "0.8125rem", color: "var(--foreground-secondary)" }}>{item.text}</span>
                </div>
              ))}
            </div>
          </div>

          <div className="sidebar-card">
            <h3>Coverage</h3>
            <div style={{ display: "flex", flexDirection: "column", gap: "0.5rem" }}>
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
                <span style={{ fontSize: "0.8125rem", color: "var(--foreground-secondary)" }}>Cities</span>
                <span className="news-headline-md" style={{ fontSize: "1rem" }}>1</span>
              </div>
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
                <span style={{ fontSize: "0.8125rem", color: "var(--foreground-secondary)" }}>Minutes Tracked</span>
                <span className="news-headline-md" style={{ fontSize: "1rem" }}>{minutesList.length}</span>
              </div>
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
                <span style={{ fontSize: "0.8125rem", color: "var(--foreground-secondary)" }}>Summaries</span>
                <span className="news-headline-md" style={{ fontSize: "1rem" }}>
                  {minutesList.filter((a) => a.has_summary).length}
                </span>
              </div>
            </div>
          </div>
        </aside>
      </div>

      <hr className="news-divider-thick" />
      <section style={{ textAlign: "center", maxWidth: "600px", margin: "0 auto", padding: "2rem 0" }}>
        <h2 className="news-headline-lg" style={{ marginBottom: "1rem" }}>About OpenCouncil</h2>
        <p className="news-body" style={{ marginBottom: "1rem" }}>
          City council minutes are full of jargon and legalese. We use AI to translate them
          into plain English so you know what's happening in your city — and when to speak up.
        </p>
        <p className="news-body" style={{ fontSize: "0.9375rem" }}>
          Currently serving <strong>{cityName}</strong>. More cities coming soon.
        </p>
      </section>
    </div>
  );
}