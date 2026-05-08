"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";

interface CityInfo {
  id: string;
  name: string;
  state: string;
  full_name?: string;
  active?: boolean;
}

interface DetectCityResponse {
  client_ip: string;
  city: CityInfo;
  all_cities: CityInfo[];
}

type ThemeMode = "system" | "light" | "dark";

export function Header() {
  const [city, setCity] = useState<CityInfo | null>(null);
  const [allCities, setAllCities] = useState<CityInfo[]>([]);
  const [theme, setTheme] = useState<ThemeMode>("system");
  const [mounted, setMounted] = useState(false);

  // --- Theme Management ---
  const applyTheme = useCallback((mode: ThemeMode) => {
    const root = document.documentElement;
    root.classList.remove("light-mode", "dark-mode");

    if (mode === "light") {
      root.classList.add("light-mode");
    } else if (mode === "dark") {
      root.classList.add("dark-mode");
    }
    // "system" = no forced class, uses prefers-color-scheme
  }, []);

  const cycleTheme = useCallback(() => {
    setTheme((prev) => {
      const next = prev === "system" ? "light" : prev === "light" ? "dark" : "system";
      applyTheme(next);
      try {
        localStorage.setItem("cch-theme", next);
      } catch {}
      return next;
    });
  }, [applyTheme]);

  // Initialize theme from localStorage
  useEffect(() => {
    setMounted(true);
    try {
      const saved = localStorage.getItem("cch-theme") as ThemeMode | null;
      if (saved) {
        setTheme(saved);
        applyTheme(saved);
      }
    } catch {}
  }, [applyTheme]);

  // --- City Detection ---
  useEffect(() => {
    // Use relative URLs — Next.js rewrites /api/* to the backend in dev,
    // and Vercel experimental services handle routing in production.
    fetch(`/api/detect-city`)
      .then((res) => res.json())
      .then((data: DetectCityResponse) => {
        setCity(data.city);
        setAllCities(data.all_cities);
      })
      .catch(() => {
        // Fallback: use default city
        setCity({ id: "paris-tx", name: "Paris", state: "TX" });
        setAllCities([{ id: "paris-tx", name: "Paris", state: "TX" }]);
      });
  }, []);

  const themeIcon = theme === "system" ? "💻" : theme === "light" ? "☀️" : "🌙";
  const themeLabel = theme === "system" ? "Auto" : theme === "light" ? "Light" : "Dark";

  return (
    <header
      style={{
        borderBottom: "1px solid var(--border)",
        background: "var(--background)",
        position: "sticky",
        top: 0,
        zIndex: 50,
      }}
    >
      {/* Top bar — newspaper name + theme toggle */}
      <div
        className="mx-auto px-4"
        style={{ maxWidth: "var(--max-width)" }}
      >
        <div
          style={{
            display: "flex",
            alignItems: "center",
            justifyContent: "space-between",
            height: "var(--header-height)",
          }}
        >
          {/* Left: Newspaper name */}
          <Link href="/" style={{ textDecoration: "none" }}>
            <div>
              <h1
                style={{
                  fontFamily: "var(--font-serif)",
                  fontSize: "1.25rem",
                  fontWeight: 700,
                  letterSpacing: "-0.03em",
                  color: "var(--foreground)",
                  lineHeight: 1,
                }}
              >
                Civic City Hub
              </h1>
              <p
                style={{
                  fontSize: "0.6875rem",
                  color: "var(--foreground-secondary)",
                  textTransform: "uppercase",
                  letterSpacing: "0.08em",
                  marginTop: 1,
                }}
              >
                Local Government, Explained
              </p>
            </div>
          </Link>

          {/* Right: City selector + nav + theme */}
          <div style={{ display: "flex", alignItems: "center", gap: "1rem" }}>
            {/* Navigation */}
            <nav style={{ display: "flex", alignItems: "center", gap: "0.75rem" }}>
              <Link
                href="/"
                className="nav-link"
                style={{
                  fontSize: "0.8125rem",
                  color: "var(--foreground-secondary)",
                  textDecoration: "none",
                  transition: "color 0.15s",
                }}
              >
                Home
              </Link>
              <Link
                href="/agendas"
                className="nav-link"
                style={{
                  fontSize: "0.8125rem",
                  color: "var(--foreground-secondary)",
                  textDecoration: "none",
                  transition: "color 0.15s",
                }}
              >
                Agendas
              </Link>
            </nav>

            {/* City selector */}
            {mounted && allCities.length > 0 && (
              <div className="city-selector">
                <select
                  value={city?.id || ""}
                  onChange={(e) => {
                    const selected = allCities.find((c) => c.id === e.target.value);
                    if (selected) setCity(selected);
                  }}
                  aria-label="Select city"
                >
                  {allCities.map((c) => (
                    <option key={c.id} value={c.id}>
                      {c.full_name || `${c.name}, ${c.state}`}
                    </option>
                  ))}
                </select>
              </div>
            )}

            {/* Theme toggle */}
            {mounted && (
              <button
                onClick={cycleTheme}
                className="theme-toggle"
                title={`Theme: ${themeLabel}`}
                aria-label={`Switch theme (currently ${themeLabel})`}
              >
                {themeIcon}
              </button>
            )}
          </div>
        </div>
      </div>

      {/* Bottom border accent */}
      <div
        style={{
          height: 3,
          background: "var(--brand)",
          width: "100%",
        }}
      />
    </header>
  );
}
