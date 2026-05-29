"use client";

import { useEffect, useState, useRef } from "react";
import { useRouter, useParams } from "next/navigation";
import {
  getSummaryDetail,
  startVerification,
  approveSummary,
  rejectSummary,
  PendingSummary,
} from "@/lib/auth";

export default function VerifyDetailPage() {
  const router = useRouter();
  const params = useParams();
  const summaryId = params.id as string;

  const [summary, setSummary] = useState<PendingSummary | null>(null);
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [editedSummary, setEditedSummary] = useState("");
  const [loading, setLoading] = useState(true);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState("");
  const [rejectReason, setRejectReason] = useState("");
  const [showRejectForm, setShowRejectForm] = useState(false);
  const [success, setSuccess] = useState("");
  const timerRef = useRef<number | null>(null);

  useEffect(() => {
    async function load() {
      try {
        const data = await getSummaryDetail(summaryId);
        setSummary(data);
        setEditedSummary(data.summary || "");

        // Start verification session timer
        const session = await startVerification(summaryId);
        setSessionId(session.session_id);
      } catch (err: any) {
        setError("Failed to load summary. Redirecting...");
        setTimeout(() => router.push("/verify"), 2000);
      } finally {
        setLoading(false);
      }
    }
    load();

    return () => {
      if (timerRef.current) clearInterval(timerRef.current);
    };
  }, [summaryId, router]);

  async function handleApprove() {
    if (!sessionId) return;
    setSubmitting(true);
    setError("");
    try {
      await approveSummary(
        summaryId,
        sessionId,
        editedSummary !== summary?.summary ? editedSummary : undefined
      );
      setSuccess("Summary approved! Social media post is being generated.");
      setTimeout(() => router.push("/verify"), 2000);
    } catch (err: any) {
      setError(err.message || "Failed to approve");
    } finally {
      setSubmitting(false);
    }
  }

  async function handleReject() {
    if (!sessionId || !rejectReason.trim()) return;
    setSubmitting(true);
    setError("");
    try {
      await rejectSummary(summaryId, sessionId, rejectReason);
      setSuccess("Summary rejected.");
      setTimeout(() => router.push("/verify"), 2000);
    } catch (err: any) {
      setError(err.message || "Failed to reject");
    } finally {
      setSubmitting(false);
    }
  }

  if (loading) {
    return (
      <div className="min-h-[60vh] flex items-center justify-center">
        <div className="skeleton h-8 w-48" />
      </div>
    );
  }

  if (!summary) {
    return (
      <div className="min-h-[60vh] flex items-center justify-center">
        <p className="text-gray-500">Summary not found.</p>
      </div>
    );
  }

  return (
    <div className="max-w-6xl mx-auto px-4 py-8">
      {/* Back link */}
      <button
        onClick={() => router.push("/verify")}
        className="text-sm text-gray-500 hover:text-gray-700 dark:hover:text-gray-300 mb-4"
      >
        ← Back to Dashboard
      </button>

      {/* Meeting info header */}
      <div className="mb-6">
        <h1 className="news-headline-1">{summary.title || "Meeting Summary"}</h1>
        <p className="text-gray-500">
          {summary.city} · {summary.meeting_date}
          {summary.category && <> · {summary.category}</>}
        </p>
      </div>

      {/* Success/Error messages */}
      {success && (
        <div className="bg-green-50 dark:bg-green-900/20 border border-green-200 dark:border-green-800 text-green-700 dark:text-green-300 px-4 py-3 rounded-md mb-4">
          {success}
        </div>
      )}
      {error && (
        <div className="bg-red-50 dark:bg-red-900/20 border border-red-200 dark:border-red-800 text-red-700 dark:text-red-300 px-4 py-3 rounded-md mb-4">
          {error}
        </div>
      )}

      {/* Split pane */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        {/* Left: AI Summary (editable) */}
        <div className="border border-gray-200 dark:border-gray-700 rounded-lg p-4">
          <h2 className="font-semibold text-lg mb-2">AI Summary</h2>
          <p className="text-xs text-gray-400 mb-3">
            Review and edit the AI-generated summary below. Correct any inaccuracies.
          </p>
          <textarea
            value={editedSummary}
            onChange={(e) => setEditedSummary(e.target.value)}
            className="w-full h-[400px] px-3 py-2 border border-gray-300 dark:border-gray-600 rounded-md bg-white dark:bg-gray-800 text-gray-900 dark:text-gray-100 font-mono text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 resize-none"
          />

          {summary.neighborhood_impact && (
            <div className="mt-4 p-3 bg-blue-50 dark:bg-blue-900/20 rounded-md">
              <p className="text-sm font-medium text-blue-700 dark:text-blue-300">
                Neighborhood Impact Hook
              </p>
              <p className="text-sm text-blue-600 dark:text-blue-400 mt-1">
                {summary.neighborhood_impact}
              </p>
            </div>
          )}
        </div>

        {/* Right: Raw OCR Text */}
        <div className="border border-gray-200 dark:border-gray-700 rounded-lg p-4">
          <h2 className="font-semibold text-lg mb-2">Raw Document Text</h2>
          <p className="text-xs text-gray-400 mb-3">
            Original OCR-extracted text from the meeting document. Use this to verify accuracy.
          </p>
          <div className="h-[400px] overflow-y-auto px-3 py-2 border border-gray-300 dark:border-gray-600 rounded-md bg-gray-50 dark:bg-gray-900 text-gray-700 dark:text-gray-300 font-mono text-sm whitespace-pre-wrap">
            {summary.raw_text || "No raw text available."}
          </div>
        </div>
      </div>

      {/* Action buttons */}
      <div className="mt-6 flex items-center gap-4">
        <button
          onClick={handleApprove}
          disabled={submitting || !!success}
          className="btn-primary"
        >
          {submitting ? "Processing..." : "✓ Approve & Post"}
        </button>

        <button
          onClick={() => setShowRejectForm(!showRejectForm)}
          disabled={submitting || !!success}
          className="btn-secondary text-red-600 dark:text-red-400 border-red-300 dark:border-red-700"
        >
          ✕ Reject
        </button>
      </div>

      {/* Reject form */}
      {showRejectForm && (
        <div className="mt-4 p-4 border border-red-200 dark:border-red-800 rounded-lg">
          <h3 className="font-semibold mb-2">Reason for Rejection</h3>
          <textarea
            value={rejectReason}
            onChange={(e) => setRejectReason(e.target.value)}
            className="w-full h-24 px-3 py-2 border border-gray-300 dark:border-gray-600 rounded-md bg-white dark:bg-gray-800 text-gray-900 dark:text-gray-100 focus:outline-none focus:ring-2 focus:ring-red-500 resize-none"
            placeholder="Explain what needs to be corrected..."
          />
          <button
            onClick={handleReject}
            disabled={submitting || !rejectReason.trim()}
            className="mt-2 btn-secondary text-red-600 dark:text-red-400 border-red-300 dark:border-red-700"
          >
            {submitting ? "Processing..." : "Confirm Rejection"}
          </button>
        </div>
      )}
    </div>
  );
}
