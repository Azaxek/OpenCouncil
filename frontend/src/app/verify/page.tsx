"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { getPendingSummaries, getVolunteerHours, getMe, logout, PendingSummary, AuthUser, VolunteerHours } from "@/lib/auth";

export default function VerifyDashboard() {
  const router = useRouter();
  const [user, setUser] = useState<AuthUser | null>(null);
  const [summaries, setSummaries] = useState<PendingSummary[]>([]);
  const [hours, setHours] = useState<VolunteerHours | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  useEffect(() => {
    async function load() {
      try {
        const [userData, summariesData, hoursData] = await Promise.all([
          getMe(),
          getPendingSummaries(),
          getVolunteerHours(),
        ]);
        setUser(userData);
        setSummaries(summariesData);
        setHours(hoursData);
      } catch (err: any) {
        setError("Not authenticated. Redirecting to login...");
        setTimeout(() => router.push("/login"), 1500);
      } finally {
        setLoading(false);
      }
    }
    load();
  }, [router]);

  async function handleLogout() {
    await logout();
    router.push("/login");
  }

  if (loading) {
    return (
      <div className="min-h-[60vh] flex items-center justify-center">
        <div className="skeleton h-8 w-48" />
      </div>
    );
  }

  if (error) {
    return (
      <div className="min-h-[60vh] flex items-center justify-center">
        <p className="text-gray-500">{error}</p>
      </div>
    );
  }

  return (
    <div className="max-w-4xl mx-auto px-4 py-8">
      {/* Header */}
      <div className="flex items-center justify-between mb-8">
        <div>
          <h1 className="news-headline-1">Verification Dashboard</h1>
          {user && (
            <p className="news-body text-gray-500 dark:text-gray-400">
              Welcome, {user.full_name}
              {user.school && <> · {user.school}</>}
            </p>
          )}
        </div>
        <div className="flex items-center gap-4">
          {hours && (
            <div className="text-right">
              <p className="text-sm text-gray-500">Total Hours</p>
              <p className="text-xl font-bold">{hours.total_hours.toFixed(1)}</p>
            </div>
          )}
          <button onClick={handleLogout} className="btn-secondary text-sm">
            Sign Out
          </button>
        </div>
      </div>

      {/* Pending Summaries */}
      <h2 className="news-headline-2 mb-4">
        Pending Review ({summaries.length})
      </h2>

      {summaries.length === 0 ? (
        <div className="text-center py-12">
          <p className="text-gray-500 text-lg">No summaries pending review.</p>
          <p className="text-gray-400 text-sm mt-2">
            Check back later when new meeting minutes are available.
          </p>
        </div>
      ) : (
        <div className="space-y-4">
          {summaries.map((s) => (
            <div
              key={s.id}
              className="border border-gray-200 dark:border-gray-700 rounded-lg p-4 hover:border-blue-400 dark:hover:border-blue-500 transition-colors cursor-pointer"
              onClick={() => router.push(`/verify/${s.id}`)}
            >
              <div className="flex items-start justify-between">
                <div className="flex-1">
                  <h3 className="font-semibold text-lg mb-1">
                    {s.title || "Untitled Meeting"}
                  </h3>
                  <p className="text-sm text-gray-500 mb-2">
                    {s.city} · {s.meeting_date}
                    {s.category && <> · {s.category}</>}
                  </p>
                  <p className="text-gray-700 dark:text-gray-300 line-clamp-2">
                    {s.neighborhood_impact || s.summary?.slice(0, 200)}
                  </p>
                </div>
                <span className="badge badge-warning shrink-0 ml-4">
                  Pending
                </span>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
