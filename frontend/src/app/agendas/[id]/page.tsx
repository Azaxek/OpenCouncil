"use client";

import Link from "next/link";
import { use, useEffect, useState } from "react";

interface AgendaItem {
  title: string;
  description: string | null;
  category: string | null;
  department: string | null;
  plain_language_summary: string | null;
  budget_impact: string | null;
}

interface AgendaDetail {
  id: string;
  city: string;
  state: string;
  meeting_date: string;
  meeting_type: string;
  title: string;
  url: string;
  pdf_url: string | null;
  document_url: string | null;
  items: AgendaItem[];
  summary: string | null;
  source: string;
}

interface SummaryData {
  summary: string;
  key_decisions: Array<{
    title: string;
    plain_english: string;
    impact: string;
    category: string;
  }>;
  budget_items: Array<{
    title: string;
    amount: string;
    description: string;
  }>;
  public_comment_opportunities: Array<{
    item: string;
    deadline: string;
    how: string;
  }>;
  items: Array<{
    title: string;
    plain_english: string;
    category: string;
    action_needed: string;
  }>;
}

// Auto-detect API base URL:
// - Local dev (localhost): empty string → Next.js rewrites /api/* to backend
// - Vercel: "/_/backend" → experimental services route to backend
const API_BASE = typeof window !== "undefined" && window.location.hostname !== "localhost"
  ? "/_/backend"
  : "";

export default function AgendaDetailPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = use(params);
  const [agenda, setAgenda] = useState<AgendaDetail | null>(null);
  const [summary, setSummary] = useState<SummaryData | null>(null);
  const [loading, setLoading] = useState(true);
  const [summarizing, setSummarizing] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    setLoading(true);
    fetch(`${API_BASE}/api/agendas/${id}`)
      .then((res) => {
        if (!res.ok) throw new Error(`API error: ${res.status}`);
        return res.json();
      })
      .then((data) => {
        // The API returns { agenda, summary }
        if (data.agenda) {
          setAgenda(data.agenda);
          setSummary(data.summary || null);
        } else {
          setAgenda(data);
        }
        setLoading(false);
      })
      .catch((e: unknown) => {
        const msg = e instanceof Error ? e.message : "Failed to load agenda";
        setError(msg);
        setLoading(false);
      });
  }, [id]);

  const handleSummarize = async () => {
    setSummarizing(true);
    try {
      const res = await fetch(`${API_BASE}/api/summarize`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ agenda_id: id, model: "deepseek-chat" }),
      });
      if (!res.ok) throw new Error(`API error: ${res.status}`);
      const data = await res.json();
      setSummary(data);
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : "Summarization failed";
      setError(msg);
    } finally {
      setSummarizing(false);
    }
  };

  const formatDate = (dateStr: string) => {
    try {
      return new Date(dateStr).toLocaleDateString("en-US", {
        weekday: "long",
        year: "numeric",
        month: "long",
        day: "numeric",
        hour: "numeric",
        minute: "2-digit",
      });
    } catch {
      return dateStr;
    }
  };

  const categoryBadge = (cat: string | null) => {
    const map: Record<string, string> = {
      "Public Hearing": "badge-red",
      "Consent Agenda": "badge-yellow",
      "New Business": "badge-green",
      "Old Business": "badge-purple",
      "Staff Reports": "badge-yellow",
      "Executive Session": "badge-red",
    };
    return map[cat || ""] || "badge-purple";
  };

  // --- Loading State ---
  if (loading) {
    return (
      <div className="space-y-6">
        <Link
          href="/agendas"
          className="news-byline"
          style={{ textDecoration: "none", display: "inline-block" }}
        >
          ← Back to agendas
        </Link>
        <div className="skeleton h-10 w-3/4" />
        <div className="skeleton h-4 w-1/2" />
        <div className="space-y-4 mt-8">
          {[1, 2, 3, 4].map((i) => (
            <div key={i} className="skeleton h-24 w-full" />
          ))}
        </div>
      </div>
    );
  }

  // --- Error State ---
  if (error) {
    return (
      <div className="space-y-4">
        <Link
          href="/agendas"
          className="news-byline"
          style={{ textDecoration: "none", display: "inline-block" }}
        >
          ← Back to agendas
        </Link>
        <div
          className="article-card"
          style={{ borderColor: "var(--accent-red)", padding: "1.25rem" }}
        >
          <p style={{ color: "var(--accent-red)", fontSize: "0.875rem" }}>{error}</p>
        </div>
      </div>
    );
  }

  // --- Not Found ---
  if (!agenda) {
    return (
      <div className="space-y-4">
        <Link
          href="/agendas"
          className="news-byline"
          style={{ textDecoration: "none", display: "inline-block" }}
        >
          ← Back to agendas
        </Link>
        <div className="article-card" style={{ padding: "3rem", textAlign: "center" }}>
          <p className="news-body">Agenda not found.</p>
        </div>
      </div>
    );
  }

  return (
    <article className="space-y-8">
      {/* ================================================================ */}
      {/* ARTICLE HEADER                                                    */}
      {/* ================================================================ */}
      <header>
        <Link
          href="/agendas"
          className="news-byline"
          style={{ textDecoration: "none", display: "inline-block", marginBottom: "1rem" }}
        >
          ← Back to agendas
        </Link>

        <div style={{ display: "flex", alignItems: "center", gap: "0.75rem", marginBottom: "0.75rem" }}>
          <span className="badge badge-brand">{agenda.meeting_type}</span>
          {summary && <span className="badge badge-green">AI Summary Available</span>}
        </div>

        <h1 className="news-headline-xl" style={{ marginBottom: "0.75rem" }}>
          {agenda.title}
        </h1>

        <div className="news-byline" style={{ marginBottom: "1rem" }}>
          {formatDate(agenda.meeting_date)} — {agenda.city}, {agenda.state}
        </div>

        {/* Action buttons */}
        <div style={{ display: "flex", gap: "0.75rem", flexWrap: "wrap" }}>
          {agenda.document_url && (
            <a
              href={agenda.document_url}
              target="_blank"
              rel="noopener noreferrer"
              className="btn btn-secondary"
            >
              View Original Document
            </a>
          )}
          <a
            href={agenda.url}
            target="_blank"
            rel="noopener noreferrer"
            className="btn btn-secondary"
          >
            View on City Website
          </a>
        </div>
      </header>

      <hr className="news-divider" />

      {/* ================================================================ */}
      {/* AI SUMMARY SECTION                                                */}
      {/* ================================================================ */}
      <section
        className="article-card article-card-featured"
        style={{ padding: "1.5rem" }}
      >
        <div
          style={{
            display: "flex",
            justifyContent: "space-between",
            alignItems: "flex-start",
            marginBottom: "1.25rem",
          }}
        >
          <div>
            <h2 className="news-headline-lg" style={{ fontSize: "1.35rem" }}>
              AI-Powered Summary
            </h2>
            <p className="news-byline" style={{ textTransform: "none", letterSpacing: "normal", marginTop: "0.25rem" }}>
              Plain-language explanation powered by DeepSeek AI
            </p>
          </div>
          {!summary && (
            <button
              onClick={handleSummarize}
              disabled={summarizing}
              className="btn btn-primary"
            >
              {summarizing ? "Summarizing..." : "Generate Summary"}
            </button>
          )}
        </div>

        {/* Loading skeleton */}
        {summarizing && (
          <div className="space-y-3">
            <div className="skeleton h-4 w-full" />
            <div className="skeleton h-4 w-5/6" />
            <div className="skeleton h-4 w-4/6" />
            <div className="skeleton h-4 w-full" />
            <div className="skeleton h-4 w-3/4" />
          </div>
        )}

        {/* Summary content */}
        {summary && (
          <div className="space-y-6">
            {/* Overview */}
            <div>
              <h3 className="news-section-tag" style={{ marginBottom: "0.5rem" }}>
                Overview
              </h3>
              <p className="news-body" style={{ fontSize: "1rem" }}>
                {summary.summary}
              </p>
            </div>

            {/* Key Decisions */}
            {summary.key_decisions.length > 0 && (
              <div>
                <h3 className="news-section-tag" style={{ marginBottom: "0.75rem" }}>
                  Key Decisions
                </h3>
                <div className="space-y-3">
                  {summary.key_decisions.map((d, i) => (
                    <div
                      key={i}
                      style={{
                        background: "var(--background-secondary)",
                        borderRadius: "0.5rem",
                        padding: "1rem",
                        border: "1px solid var(--border)",
                      }}
                    >
                      <div style={{ display: "flex", alignItems: "flex-start", justifyContent: "space-between", gap: "0.5rem" }}>
                        <h4 className="news-headline-md" style={{ fontSize: "0.9375rem" }}>
                          {d.title}
                        </h4>
                        <span className={`badge text-xs ${categoryBadge(d.category)}`}>
                          {d.category}
                        </span>
                      </div>
                      <p className="news-body" style={{ fontSize: "0.875rem", marginTop: "0.375rem" }}>
                        {d.plain_english}
                      </p>
                      {d.impact && (
                        <p style={{ fontSize: "0.8125rem", color: "var(--foreground-secondary)", marginTop: "0.5rem", fontStyle: "italic" }}>
                          Affects: {d.impact}
                        </p>
                      )}
                    </div>
                  ))}
                </div>
              </div>
            )}

            {/* Budget Items */}
            {summary.budget_items.length > 0 && (
              <div>
                <h3 className="news-section-tag" style={{ marginBottom: "0.75rem" }}>
                  Budget Items
                </h3>
                <div className="space-y-2">
                  {summary.budget_items.map((b, i) => (
                    <div
                      key={i}
                      style={{
                        display: "flex",
                        justifyContent: "space-between",
                        alignItems: "center",
                        background: "var(--background-secondary)",
                        borderRadius: "0.5rem",
                        padding: "0.875rem",
                        border: "1px solid var(--border)",
                      }}
                    >
                      <div>
                        <p style={{ fontSize: "0.875rem", fontWeight: 500 }}>{b.title}</p>
                        <p style={{ fontSize: "0.8125rem", color: "var(--foreground-secondary)" }}>
                          {b.description}
                        </p>
                      </div>
                      <span
                        style={{
                          fontSize: "0.875rem",
                          fontFamily: "var(--font-mono)",
                          fontWeight: 700,
                          color: "var(--accent-yellow)",
                          whiteSpace: "nowrap",
                          marginLeft: "1rem",
                        }}
                      >
                        {b.amount}
                      </span>
                    </div>
                  ))}
                </div>
              </div>
            )}

            {/* Public Comment Opportunities */}
            {summary.public_comment_opportunities.length > 0 && (
              <div>
                <h3 className="news-section-tag" style={{ marginBottom: "0.75rem" }}>
                  Public Comment Opportunities
                </h3>
                <div className="space-y-2">
                  {summary.public_comment_opportunities.map((c, i) => (
                    <div
                      key={i}
                      style={{
                        background: "var(--background-secondary)",
                        borderRadius: "0.5rem",
                        padding: "0.875rem",
                        border: "1px solid var(--border)",
                      }}
                    >
                      <p style={{ fontSize: "0.875rem", fontWeight: 500 }}>{c.item}</p>
                      <p style={{ fontSize: "0.8125rem", color: "var(--foreground-secondary)", marginTop: "0.25rem" }}>
                        {c.how}
                      </p>
                      {c.deadline && (
                        <p style={{ fontSize: "0.8125rem", color: "var(--accent-yellow)", marginTop: "0.25rem" }}>
                          Deadline: {c.deadline}
                        </p>
                      )}
                    </div>
                  ))}
                </div>
              </div>
            )}
          </div>
        )}

        {/* Empty state */}
        {!summary && !summarizing && (
          <p className="news-body" style={{ textAlign: "center", padding: "2rem 0", fontSize: "0.9375rem" }}>
            Click &ldquo;Generate Summary&rdquo; to get an AI-powered plain-language
            explanation of this agenda.
          </p>
        )}
      </section>

      {/* ================================================================ */}
      {/* AGENDA ITEMS                                                      */}
      {/* ================================================================ */}
      <section>
        <div className="section-header">
          <span className="news-section-tag">Agenda Items</span>
          <span style={{ fontSize: "0.8125rem", color: "var(--foreground-secondary)" }}>
            {agenda.items.length} item{agenda.items.length !== 1 ? "s" : ""}
          </span>
        </div>

        {agenda.items.length === 0 ? (
          <div className="article-card" style={{ padding: "2rem", textAlign: "center" }}>
            <p className="news-body" style={{ fontSize: "0.9375rem" }}>
              No individual agenda items parsed. View the original PDF for full details.
            </p>
          </div>
        ) : (
          <div className="space-y-3">
            {agenda.items.map((item, i) => (
              <div key={i} className="article-card" style={{ padding: "1.25rem" }}>
                <div style={{ display: "flex", gap: "0.75rem" }}>
                  <span
                    style={{
                      fontSize: "0.75rem",
                      color: "var(--foreground-secondary)",
                      fontFamily: "var(--font-mono)",
                      minWidth: "1.5rem",
                      textAlign: "right",
                    }}
                  >
                    {i + 1}.
                  </span>
                  <div style={{ flex: 1, minWidth: 0 }}>
                    <div style={{ display: "flex", alignItems: "center", gap: "0.5rem", flexWrap: "wrap", marginBottom: "0.25rem" }}>
                      <h3 className="news-headline-md" style={{ fontSize: "0.9375rem" }}>
                        {item.title}
                      </h3>
                      {item.category && (
                        <span className={`badge ${categoryBadge(item.category)}`}>
                          {item.category}
                        </span>
                      )}
                    </div>
                    {item.description && (
                      <p className="news-body" style={{ fontSize: "0.875rem", marginTop: "0.25rem" }}>
                        {item.description}
                      </p>
                    )}
                    {item.plain_language_summary && (
                      <p
                        style={{
                          fontSize: "0.875rem",
                          color: "var(--brand)",
                          marginTop: "0.5rem",
                          fontStyle: "italic",
                          padding: "0.5rem 0.75rem",
                          background: "var(--brand-light)",
                          borderRadius: "0.375rem",
                        }}
                      >
                        💡 {item.plain_language_summary}
                      </p>
                    )}
                  </div>
                </div>
              </div>
            ))}
          </div>
        )}
      </section>
    </article>
  );
}
