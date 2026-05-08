"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";

interface AgendaListItem {
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

// Auto-detect API base URL:
// - Local dev (localhost): empty string → Next.js rewrites /api/* to backend
// - Vercel: "/_/backend" → experimental services route to backend
const API_BASE = typeof window !== "undefined" && window.location.hostname !== "localhost"
  ? "/_/backend"
  : "";

export default function AgendasPage() {
  const [agendas, setAgendas] = useState<AgendaListItem[]>([]);
  const [cityInfo, setCityInfo] = useState<CityInfo | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [fetching, setFetching] = useState(false);

  const loadAgendas = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [agendasRes, cityRes] = await Promise.all([
        fetch(`${API_BASE}/api/agendas?limit=20`),
        fetch(`${API_BASE}/api/detect-city`).catch(() => null),
      ]);

      if (!agendasRes.ok) throw new Error(`API error: ${agendasRes.status}`);
      const agendasData = await agendasRes.json();
      setAgendas(agendasData.agendas || []);

      if (cityRes) {
        const cityData = await cityRes.json();
        setCityInfo(cityData.city);
      }
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : "Failed to load agendas";
      setError(msg);
    } finally {
      setLoading(false);
    }
  }, []);

  const fetchLatest = async () => {
    setFetching(true);
    try {
      const res = await fetch(`${API_BASE}/api/agendas/fetch-latest`, {
        method: "POST",
      });
      if (!res.ok) throw new Error(`API error: ${res.status}`);
      await loadAgendas();
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : "Failed to fetch latest";
      setError(msg);
    } finally {
      setFetching(false);
    }
  };

  useEffect(() => {
    loadAgendas();
  }, [loadAgendas]);

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
          City Council Agendas
        </h1>
        <p className="news-body" style={{ fontSize: "1rem" }}>
          {cityName} — Recent and upcoming meeting agendas with AI-powered plain-language summaries
        </p>
      </div>

      <hr className="news-divider" />

      {/* Controls */}
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
        <span className="news-section-tag">
          {agendas.length > 0
            ? `${agendas.length} agenda${agendas.length !== 1 ? "s" : ""} found`
            : "No agendas yet"}
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
            <>🔄 Fetch Latest Agenda</>
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
          <button onClick={loadAgendas} className="btn btn-secondary">
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
      {!loading && !error && agendas.length === 0 && (
        <div className="article-card" style={{ padding: "3rem", textAlign: "center" }}>
          <p className="news-body" style={{ marginBottom: "1rem" }}>
            No agendas found yet. Click &ldquo;Fetch Latest Agenda&rdquo; to pull the
            most recent agenda from {cityName}.
          </p>
          <button onClick={fetchLatest} disabled={fetching} className="btn btn-primary">
            Fetch Latest Agenda
          </button>
        </div>
      )}

      {/* Agenda list */}
      {!loading && agendas.length > 0 && (
        <div className="space-y-3">
          {agendas.map((agenda, index) => (
            <Link
              key={agenda.id}
              href={`/agendas/${agenda.id}`}
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
                      {agenda.has_summary && (
                        <span className="badge badge-green" style={{ fontSize: "0.625rem" }}>Summarized</span>
                      )}
                    </div>
                    <h3 className="news-headline-md" style={{ fontSize: "1.1rem" }}>
                      {agenda.title}
                    </h3>
                    <p className="news-byline" style={{ marginTop: "0.25rem" }}>
                      {formatDate(agenda.meeting_date)}
                      {agenda.meeting_type && ` — ${agenda.meeting_type}`}
                    </p>
                  </div>
                  <div style={{ display: "flex", alignItems: "center", gap: "0.5rem", flexShrink: 0 }}>
                    {agenda.document_url && (
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
