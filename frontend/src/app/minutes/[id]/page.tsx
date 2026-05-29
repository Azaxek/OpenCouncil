"use client";

import Link from "next/link";
import { use, useEffect, useState } from "react";
import { useRouter } from "next/navigation";

interface MinutesDetail {
  id: string;
  city: string;
  state: string;
  meeting_date: string;
  meeting_type: string;
  title: string;
  url: string;
  document_url: string | null;
  raw_text: string | null;
  summary: string | null;
  source: string;
}

interface SummaryData {
  big_picture: string;
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
  what_you_can_do: Array<{
    action: string;
    who: string;
  }>;
}

// API base URL — always empty string.
// Local dev: Next.js rewrites in next.config.ts proxy /api/* to localhost:8000
// Vercel: vercel.json routes /api/* to the Python serverless function
const API_BASE = "";

export default function MinutesDetailPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = use(params);
  const router = useRouter();
  const [minutes, setMinutes] = useState<MinutesDetail | null>(null);
  const [summary, setSummary] = useState<SummaryData | null>(null);
  const [loading, setLoading] = useState(true);
  const [summarizing, setSummarizing] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    fetch(`${API_BASE}/api/minutes/${id}`)
      .then((res) => {
        if (res.status === 404) {
          // Minutes ID no longer exists (e.g., after database reset).
          // Redirect to minutes list to break the retry cycle.
          router.replace("/minutes");
          return null;
        }
        if (!res.ok) throw new Error(`API error: ${res.status}`);
        return res.json();
      })
      .then((data) => {
        if (cancelled || data === null) return;
        // The API returns { minutes, summary }
        if (data.minutes) {
          setMinutes(data.minutes);
          setSummary(data.summary || null);
        } else {
          setMinutes(data);
        }
        setLoading(false);
      })
      .catch((e: unknown) => {
        if (cancelled) return;
        const msg = e instanceof Error ? e.message : "Failed to load minutes";
        setError(msg);
        setLoading(false);
      });
    return () => { cancelled = true; };
  }, [id, router]);

  const handleSummarize = async () => {
    setSummarizing(true);
    try {
      const res = await fetch(`${API_BASE}/api/minutes/summarize`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ minutes_id: id, model: "deepseek-chat" }),
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
      // Life-Centric categories
      "Your Neighborhood": "badge-green",
      "Your Tax Dollars": "badge-yellow",
      "City Calendar": "badge-purple",
      "Your Commute": "badge-blue",
      "Your Utilities": "badge-blue",
      "Your Parks & Trails": "badge-green",
      "Your Safety": "badge-red",
      "Meeting Logistics": "badge-purple",
      "Community Briefing": "badge-blue",
      "City Planning": "badge-yellow",
      "Council Action": "badge-green",
    };
    return map[cat || ""] || "badge-purple";
  };

  // --- Loading State ---
  if (loading) {
    return (
      <div className="space-y-6">
        <Link
          href="/minutes"
          className="news-byline"
          style={{ textDecoration: "none", display: "inline-block" }}
        >
          ← Back to minutes
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
          href="/minutes"
          className="news-byline"
          style={{ textDecoration: "none", display: "inline-block" }}
        >
          ← Back to minutes
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
  if (!minutes) {
    return (
      <div className="space-y-4">
        <Link
          href="/minutes"
          className="news-byline"
          style={{ textDecoration: "none", display: "inline-block" }}
        >
          ← Back to minutes
        </Link>
        <div className="article-card" style={{ padding: "3rem", textAlign: "center" }}>
          <p className="news-body">Minutes not found.</p>
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
          href="/minutes"
          className="news-byline"
          style={{ textDecoration: "none", display: "inline-block", marginBottom: "1rem" }}
        >
          ← Back to minutes
        </Link>

        <div style={{ display: "flex", alignItems: "center", gap: "0.75rem", marginBottom: "0.75rem" }}>
          <span className="badge badge-brand">{minutes.meeting_type}</span>
          {summary && <span className="badge badge-green">AI Summary Available</span>}
        </div>

        <h1 className="news-headline-xl" style={{ marginBottom: "0.75rem" }}>
          {minutes.title}
        </h1>

        <div className="news-byline" style={{ marginBottom: "1rem" }}>
          {formatDate(minutes.meeting_date)} — {minutes.city}, {minutes.state}
        </div>

        {/* Action buttons */}
        <div style={{ display: "flex", gap: "0.75rem", flexWrap: "wrap" }}>
          {minutes.document_url && (
            <a
              href={minutes.document_url}
              target="_blank"
              rel="noopener noreferrer"
              className="btn btn-secondary"
            >
              View Original Document
            </a>
          )}
          <a
            href={minutes.url}
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
              Plain-language explanation powered by Groq AI (Llama 8B)
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
            {/* Big Picture — TL;DR at the very top */}
            {summary.big_picture && (
              <div
                style={{
                  background: "linear-gradient(135deg, var(--accent-blue), var(--accent-purple))",
                  borderRadius: "0.75rem",
                  padding: "1.25rem 1.5rem",
                  color: "#000",
                }}
              >
                <p
                  style={{
                    fontSize: "1.125rem",
                    fontWeight: 600,
                    lineHeight: 1.5,
                    margin: 0,
                  }}
                >
                  🏛️ {summary.big_picture}
                </p>
              </div>
            )}

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
                          🏡 How this affects you: {d.impact}
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

            {/* What You Can Do */}
            {summary.what_you_can_do && summary.what_you_can_do.length > 0 && (
              <div
                style={{
                  background: "var(--background-secondary)",
                  borderRadius: "0.75rem",
                  padding: "1.25rem 1.5rem",
                  border: "1px solid var(--border)",
                }}
              >
                <h3 className="news-section-tag" style={{ marginBottom: "0.75rem" }}>
                  ✅ What You Can Do
                </h3>
                <div className="space-y-3">
                  {summary.what_you_can_do.map((w, i) => (
                    <div key={i} style={{ display: "flex", alignItems: "flex-start", gap: "0.75rem" }}>
                      <span style={{ fontSize: "1.25rem", lineHeight: 1.4, flexShrink: 0 }}>👉</span>
                      <div>
                        <p style={{ fontSize: "0.9375rem", lineHeight: 1.5, margin: 0 }}>
                          {w.action}
                        </p>
                        {w.who && (
                          <p style={{ fontSize: "0.8125rem", color: "var(--foreground-secondary)", marginTop: "0.25rem" }}>
                            For: {w.who}
                          </p>
                        )}
                      </div>
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
            explanation of these minutes.
          </p>
        )}
      </section>

      {/* ================================================================ */}
      {/* RAW TEXT SECTION                                                  */}
      {/* ================================================================ */}
      {minutes.raw_text && (
        <section>
          <div className="section-header">
            <span className="news-section-tag">Document Text</span>
          </div>
          <div
            className="article-card"
            style={{
              padding: "1.25rem",
              maxHeight: "400px",
              overflowY: "auto",
              fontFamily: "var(--font-mono)",
              fontSize: "0.8125rem",
              whiteSpace: "pre-wrap",
              lineHeight: 1.6,
            }}
          >
            {minutes.raw_text}
          </div>
        </section>
      )}
    </article>
  );
}
