// Auth utility for CivillySimplified volunteer portal

const API_BASE = "/api";

export interface AuthUser {
  user_id: string;
  email: string;
  full_name: string;
  school?: string;
  hours_earned: number;
}

export interface LoginResponse {
  access_token: string;
  token_type: string;
  user: AuthUser;
}

export interface PendingSummary {
  id: string;
  summary: string;
  raw_text: string;
  category?: string;
  neighborhood_impact?: string;
  meeting_date: string;
  title: string;
  city: string;
}

export interface VerificationSession {
  id: string;
  started_at: string;
  ended_at?: string;
  duration_seconds?: number;
  action?: string;
  notes?: string;
}

export interface VolunteerHours {
  total_hours: number;
  sessions: VerificationSession[];
}

// Token management
function getToken(): string | null {
  if (typeof window === "undefined") return null;
  return localStorage.getItem("civic_token");
}

function setToken(token: string): void {
  localStorage.setItem("civic_token", token);
}

function clearToken(): void {
  localStorage.removeItem("civic_token");
}

function getAuthHeaders(): Record<string, string> {
  const token = getToken();
  return token ? { Authorization: `Bearer ${token}` } : {};
}

// Auth API calls
export async function login(email: string, password: string): Promise<LoginResponse> {
  const res = await fetch(`${API_BASE}/auth/login`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ email, password }),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: "Login failed" }));
    throw new Error(err.detail || "Login failed");
  }
  const data = await res.json();
  setToken(data.access_token);
  return data;
}

export async function signup(
  email: string,
  password: string,
  fullName: string,
  school: string
): Promise<{ user_id: string; email: string }> {
  const res = await fetch(`${API_BASE}/auth/signup`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ email, password, full_name: fullName, school }),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: "Signup failed" }));
    throw new Error(err.detail || "Signup failed");
  }
  return res.json();
}

export async function getMe(): Promise<AuthUser> {
  const res = await fetch(`${API_BASE}/auth/me`, {
    headers: getAuthHeaders(),
  });
  if (!res.ok) throw new Error("Not authenticated");
  return res.json();
}

export async function logout(): Promise<void> {
  clearToken();
}

// Verification API calls
export async function getPendingSummaries(): Promise<PendingSummary[]> {
  const res = await fetch(`${API_BASE}/verify/pending`, {
    headers: getAuthHeaders(),
  });
  if (!res.ok) throw new Error("Failed to fetch pending summaries");
  return res.json();
}

export async function getSummaryDetail(summaryId: string): Promise<PendingSummary> {
  const res = await fetch(`${API_BASE}/verify/${summaryId}`, {
    headers: getAuthHeaders(),
  });
  if (!res.ok) throw new Error("Failed to fetch summary detail");
  return res.json();
}

export async function startVerification(summaryId: string): Promise<{ session_id: string }> {
  const res = await fetch(`${API_BASE}/verify/${summaryId}/start`, {
    method: "POST",
    headers: { ...getAuthHeaders(), "Content-Type": "application/json" },
  });
  if (!res.ok) throw new Error("Failed to start verification");
  return res.json();
}

export async function approveSummary(
  summaryId: string,
  sessionId: string,
  editedSummary?: string,
  notes?: string
): Promise<{ success: boolean }> {
  const res = await fetch(`${API_BASE}/verify/${summaryId}/approve`, {
    method: "POST",
    headers: { ...getAuthHeaders(), "Content-Type": "application/json" },
    body: JSON.stringify({
      session_id: sessionId,
      edited_summary: editedSummary,
      notes,
    }),
  });
  if (!res.ok) throw new Error("Failed to approve summary");
  return res.json();
}

export async function rejectSummary(
  summaryId: string,
  sessionId: string,
  reason: string
): Promise<{ success: boolean }> {
  const res = await fetch(`${API_BASE}/verify/${summaryId}/reject`, {
    method: "POST",
    headers: { ...getAuthHeaders(), "Content-Type": "application/json" },
    body: JSON.stringify({
      session_id: sessionId,
      reason,
    }),
  });
  if (!res.ok) throw new Error("Failed to reject summary");
  return res.json();
}

export async function getVolunteerHours(): Promise<VolunteerHours> {
  const res = await fetch(`${API_BASE}/verify/hours`, {
    headers: getAuthHeaders(),
  });
  if (!res.ok) throw new Error("Failed to fetch hours");
  return res.json();
}

export { getToken, clearToken };
