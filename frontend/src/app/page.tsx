"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";

interface HealthResponse {
  status: string;
  city: string;
  llm_available: boolean;
  llm_provider: string;
  storage: string;
}

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

interface DetectCityResponse {
  client_ip: string;
  city: CityInfo;
  all_cities: CityInfo[];
}

const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

export default function HomePage() {
  const [health, setHealth] = useState<HealthResponse | null>(null);
  const [agendas, setAgendas] = useState<AgendaListItem[]>([]);
  const [cityInfo, setCityInfo] = useState<CityInfo | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    Promise.all([
      // Health check
      fetch(`${API_BASE}/health`)
        .then((res) => res.json())
        .catch(() => null),
      // City detection
      fetch(`${API_BASE}/api/detect-city`)
        .then((res) => res.json())
        .catch(() => null),
      // Recent agendas
      fetch(`${API_BASE}/api/agendas?limit=5`)
        .then((res) => res.json())
        .catch(() => ({ agendas: [] })),
    ])
      .then(([healthData, cityData, agendasData]) => {
        setHealth(healthData);
        if (cityData) setCityInfo(cityData.city);
        setAgendas(agendasData.agendas || []);
        setLoading(false);
      })
      .catch(() => setLoading(false));
  }, []);

  const formatDate = (dateStr: string | null) => {
    if (!dateStr) return "";
    try {
      return new Date(dateStr).toLocaleDateString("en-US", {
        month: "long",
        day: "numeric",
        year: "numeric",
      });
    } catch {
      return dateStr;
    }
  };

  const cityName = cityInfo?.full_name || (cityInfo ? `${cityInfo.name}, ${cityInfo.state}` : "Paris, Texas");
  const latestAgenda = agendas[0];
  const otherAgendas = agendas.slice(1, 4);

  return (
    <div className="space-y-8">
      {/* ================================================================ */}
      {/* TOP STORY — Featured Agenda                                       */}
      {/* ================================================================ */}
      <section>
        {loading ? (
          <div className="space-y-4">
            <div className="skeleton h-8 w-1/3" />
            <div className="skeleton h-64 w-full" />
          </div>
        ) : latestAgenda ? (
          <Link href={`/agendas/${latestAgenda.id}`} style={{ textDecoration: "none" }}>
            <article
              className="article-card article-card-featured"
              style={{ padding: "2rem" }}
            >
              <div style={{ display: "flex", flexDirection: "column", gap: "1rem" }}>
                <div style={{ display: "flex", alignItems: "center", gap: "0.75rem" }}>
                  <span className="news-section-tag">Featured Agenda</span>
                  {latestAgenda.has_summary && (
                    <span className="badge badge-brand">AI Summary Available</span>
                  )}
                </div>
                <h2 className="news-headline-xl">
                  {latestAgenda.title}
                </h2>
                <div className="news-byline">
                  {cityName} — {formatDate(latestAgenda.meeting_date)}
                  {latestAgenda.meeting_type && ` — ${latestAgenda.meeting_type}`}
                </div>
                <p className="news-body" style={{ marginTop: "0.5rem" }}>
                  {latestAgenda.has_summary
                    ? "An AI-powered plain-language summary is available for this agenda. Read the key decisions, budget items, and public comment opportunities."
                    : "View the full agenda with AI-powered plain-language summaries of each item."}
                </p>
                <div>
                  <span className="btn btn-primary">
                    Read Full Coverage →
                  </span>
                </div>
              </div>
            </article>
          </Link>
        ) : (
          <article
            className="article-card"
            style={{ padding: "2rem", textAlign: "center" }}
          >
            <h2 className="news-headline-lg" style={{ marginBottom: "0.75rem" }}>
              Welcome to Civic City Hub
            </h2>
            <p className="news-body">
              We're currently fetching the latest agenda from {cityName}.
              Check back soon for plain-language summaries of city council meetings.
            </p>
          </article>
        )}
      </section>

      {/* ================================================================ */}
      {/* NEWS GRID — More Agendas + Sidebar                                */}
      {/* ================================================================ */}
      <div className="news-layout">
        {/* Main content */}
        <div className="space-y-6">
          {/* Section header */}
          <div className="section-header">
            <span className="news-section-tag">Latest Agendas</span>
          </div>

          {/* Agenda cards */}
          {loading ? (
            <div className="space-y-4">
              {[1, 2, 3].map((i) => (
                <div key={i} className="skeleton h-24 w-full" />
              ))}
            </div>
          ) : otherAgendas.length > 0 ? (
            <div className="space-y-4">
              {otherAgendas.map((agenda) => (
                <Link
                  key={agenda.id}
                  href={`/agendas/${agenda.id}`}
                  style={{ textDecoration: "none" }}
                >
                  <article className="article-card" style={{ padding: "1.25rem" }}>
                    <div
                      style={{
                        display: "flex",
                        justifyContent: "space-between",
                        alignItems: "flex-start",
                        gap: "1rem",
                      }}
                    >
                      <div style={{ flex: 1, minWidth: 0 }}>
                        <h3 className="news-headline-md" style={{ marginBottom: "0.25rem" }}>
                          {agenda.title}
                        </h3>
                        <p className="news-byline">
                          {formatDate(agenda.meeting_date)}
                          {agenda.meeting_type && ` — ${agenda.meeting_type}`}
                        </p>
                      </div>
                      <div style={{ display: "flex", alignItems: "center", gap: "0.5rem", flexShrink: 0 }}>
                        {agenda.has_summary && (
                          <span className="badge badge-brand">AI</span>
                        )}
                        <span style={{ color: "var(--foreground-secondary)", fontSize: "0.875rem" }}>
                          →
                        </span>
                      </div>
                    </div>
                  </article>
                </Link>
              ))}
            </div>
          ) : (
            <div className="article-card" style={{ padding: "2rem", textAlign: "center" }}>
              <p className="news-body" style={{ marginBottom: "1rem" }}>
                No agendas available yet.
              </p>
              <Link href="/agendas" className="btn btn-primary">
                Browse Agendas
              </Link>
            </div>
          )}

          {/* View all link */}
          {agendas.length > 0 && (
            <div style={{ textAlign: "center" }}>
              <Link href="/agendas" className="btn btn-secondary">
                View All Agendas →
              </Link>
            </div>
          )}
        </div>

        {/* ================================================================ */}
        {/* SIDEBAR                                                          */}
        {/* ================================================================ */}
        <aside className="space-y-6">
          {/* City Info */}
          <div className="sidebar-card">
            <h3>Your City</h3>
            <p className="news-headline-md" style={{ marginBottom: "0.25rem" }}>
              {cityName}
            </p>
            <p className="news-byline" style={{ textTransform: "none", letterSpacing: "normal" }}>
              {health
                ? `API: ${health.status === "ok" ? "Connected" : "Offline"}`
                : "Connecting..."}
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

          {/* How It Works */}
          <div className="sidebar-card">
            <h3>How It Works</h3>
            <div style={{ display: "flex", flexDirection: "column", gap: "0.75rem" }}>
              {[
                { step: "1", text: "City publishes agenda on their website" },
                { step: "2", text: "We fetch and parse the PDF automatically" },
                { step: "3", text: "AI translates legalese into plain English" },
                { step: "4", text: "You stay informed about your local government" },
              ].map((item) => (
                <div key={item.step} style={{ display: "flex", gap: "0.625rem", alignItems: "flex-start" }}>
                  <span
                    className="badge badge-brand"
                    style={{ minWidth: "1.5rem", textAlign: "center" }}
                  >
                    {item.step}
                  </span>
                  <span style={{ fontSize: "0.8125rem", color: "var(--foreground-secondary)" }}>
                    {item.text}
                  </span>
                </div>
              ))}
            </div>
          </div>

          {/* Stats */}
          <div className="sidebar-card">
            <h3>Coverage</h3>
            <div style={{ display: "flex", flexDirection: "column", gap: "0.5rem" }}>
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
                <span style={{ fontSize: "0.8125rem", color: "var(--foreground-secondary)" }}>Cities</span>
                <span className="news-headline-md" style={{ fontSize: "1rem" }}>1</span>
              </div>
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
                <span style={{ fontSize: "0.8125rem", color: "var(--foreground-secondary)" }}>Agendas Tracked</span>
                <span className="news-headline-md" style={{ fontSize: "1rem" }}>{agendas.length}</span>
              </div>
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
                <span style={{ fontSize: "0.8125rem", color: "var(--foreground-secondary)" }}>Summaries</span>
                <span className="news-headline-md" style={{ fontSize: "1rem" }}>
                  {agendas.filter((a) => a.has_summary).length}
                </span>
              </div>
            </div>
          </div>
        </aside>
      </div>

      {/* ================================================================ */}
      {/* ABOUT SECTION                                                     */}
      {/* ================================================================ */}
      <hr className="news-divider-thick" />
      <section style={{ textAlign: "center", maxWidth: "600px", margin: "0 auto", padding: "2rem 0" }}>
        <h2 className="news-headline-lg" style={{ marginBottom: "1rem" }}>
          About Civic City Hub
        </h2>
        <p className="news-body" style={{ marginBottom: "1rem" }}>
          City council agendas are full of jargon and legalese. We use AI to translate them
          into plain English so you know what's happening in your city — and when to speak up.
        </p>
        <p className="news-body" style={{ fontSize: "0.9375rem" }}>
          Currently serving <strong>{cityName}</strong>. More cities coming soon.
        </p>
      </section>
    </div>
  );
}
