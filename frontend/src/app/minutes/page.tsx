"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";

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

// API base URL — always empty string.
// Local dev: Next.js rewrites in next.config.ts proxy /api/* to localhost:8000
// Vercel: vercel.json routes /api/* to the Python serverless function
const API_BASE = "";

export default function MinutesPage() {
  const [minutesList, setMinutesList] = useState<MinutesListItem[]>([]);
  const [cityInfo, setCityInfo] = useState<CityInfo | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [fetching, setFetching] = useState(false);

  const loadMinutes = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [minutesRes, cityRes] = await Promise.all([
        fetch(`${API_BASE}/api/minutes?limit=20`),
        fetch(`${API_BASE}/api/detect-city`).catch(() => null),
      ]);

      if (!minutesRes.ok) throw new Error(`API error: ${minutesRes.status}`);
      const minutesData = await minutesRes.json();
      setMinutesList(minutesData.minutes || []);

      if (cityRes) {
        const cityData = await cityRes.json();
        setCityInfo(cityData.city);
      }
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : "Failed to load minutes";
      setError(msg);
    } finally {
      setLoading(false);
    }
  }, []);

  const fetchLatest = async () => {
    setFetching(true);
    try {
      const res = await fetch(`${API_BASE}/api/minutes/fetch-latest`, {
        method: "POST",
      });
      if (!res.ok) throw new Error(`API error: ${res.status}`);
      await loadMinutes();
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : "Failed to fetch latest";
      setError(msg);
    } finally {
      setFetching(false);
    }
  };

  useEffect(() => {
    loadMinutes();
  }, [loadMinutes]);

  const formatDate = (dateStr: string | null) => {
    if (!dateStr) return "Date TBD";
    try {
      return new Date(dateStr).toLocaleDateString("en-US", {
        weekday: "long",
        year: "numeric",
        month: "long",
        day: "numeric",
      });
    } catch {
      return dateStr;
    }
  };

  const cityName = cityInfo?.full_name || (cityInfo ? `${cityInfo.name}, ${cityInfo.state}` : "Paris, Texas");

  return (
    <div className="space-y-8">
      {/* Header */}
      <div>
        <h1 className="news-headline-xl" style={{ marginBottom: "0.5rem" }}>
          City Council Minutes
        </h1>
        <p className="news-body" style={{ fontSize: "1rem" }}>
          {cityName} — Official records of city council meetings with AI-powered plain-language summaries
        </p>
      </div>

      <hr className="news-divider" />

      {/* Controls */}
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
        <span className="news-section-tag">
          {minutesList.length > 0
            ? `${minutesList.length} minute${minutesList.length !== 1 ? "s" : ""} found`
            : "No minutes yet"}
        </span>
        <button
          onClick={fetchLatest}
          disabled={fetching}
          className="btn btn-primary"
        >
          {fetching ? (
            <>
              <span className="w-4 h-4 border-2 border-white/30 border-t-white rounded-full animate-spin" />
              Fetching...
            </>
          ) : (
            <>🔄 Fetch Latest Minutes</>
          )}
        </button>
      </div>

      {/* Error */}
      {error && (
        <div
          className="article-card"
          style={{
            borderColor: "var(--accent-red)",
            padding: "1.25rem",
          }}
        >
          <p style={{ color: "var(--accent-red)", fontSize: "0.875rem", marginBottom: "0.75rem" }}>
            {error}
          </p>
          <button onClick={loadMinutes} className="btn btn-secondary">
            Retry
          </button>
        </div>
      )}

      {/* Loading */}
      {loading && (
        <div className="space-y-4">
          {[1, 2, 3].map((i) => (
            <div key={i} className="article-card" style={{ padding: "1.25rem" }}>
              <div className="skeleton h-5 w-3/4 mb-3" />
              <div className="skeleton h-4 w-1/2" />
            </div>
          ))}
        </div>
      )}

      {/* Empty state */}
      {!loading && !error && minutesList.length === 0 && (
        <div className="article-card" style={{ padding: "3rem", textAlign: "center" }}>
          <p className="news-body" style={{ marginBottom: "1rem" }}>
            No minutes found yet. Click &ldquo;Fetch Latest Minutes&rdquo; to pull the
            most recent minutes from {cityName}.
          </p>
          <button onClick={fetchLatest} disabled={fetching} className="btn btn-primary">
            Fetch Latest Minutes
          </button>
        </div>
      )}

      {/* Minutes list */}
      {!loading && minutesList.length > 0 && (
        <div className="space-y-3">
          {minutesList.map((minutes, index) => (
            <Link
              key={minutes.id}
              href={`/minutes/${minutes.id}`}
              style={{ textDecoration: "none" }}
            >
              <article
                className={`article-card ${index === 0 ? "article-card-featured" : ""}`}
                style={{ padding: "1.25rem" }}
              >
                <div
                  style={{
                    display: "flex",
                    justifyContent: "space-between",
                    alignItems: "flex-start",
                    gap: "1rem",
                  }}
                >
                  <div style={{ flex: 1, minWidth: 0 }}>
                    <div style={{ display: "flex", alignItems: "center", gap: "0.5rem", marginBottom: "0.25rem" }}>
                      {index === 0 && (
                        <span className="badge badge-brand" style={{ fontSize: "0.625rem" }}>Latest</span>
                      )}
                      {minutes.has_summary && (
                        <span className="badge badge-green" style={{ fontSize: "0.625rem" }}>Summarized</span>
                      )}
                    </div>
                    <h3 className="news-headline-md" style={{ fontSize: "1.1rem" }}>
                      {minutes.title}
                    </h3>
                    <p className="news-byline" style={{ marginTop: "0.25rem" }}>
                      {formatDate(minutes.meeting_date)}
                      {minutes.meeting_type && ` — ${minutes.meeting_type}`}
                    </p>
                  </div>
                  <div style={{ display: "flex", alignItems: "center", gap: "0.5rem", flexShrink: 0 }}>
                    {minutes.document_url && (
                      <span className="badge badge-purple" style={{ fontSize: "0.625rem" }}>PDF</span>
                    )}
                    <span style={{ color: "var(--foreground-secondary)", fontSize: "1.25rem" }}>
                      →
                    </span>
                  </div>
                </div>
              </article>
            </Link>
          ))}
        </div>
      )}
    </div>
  );
}
