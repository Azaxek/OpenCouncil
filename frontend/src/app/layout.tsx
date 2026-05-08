import type { Metadata } from "next";
import { Inter, JetBrains_Mono } from "next/font/google";
import "./globals.css";
import { Header } from "./header";

const inter = Inter({
  variable: "--font-inter",
  subsets: ["latin"],
});

const jetbrainsMono = JetBrains_Mono({
  variable: "--font-mono",
  subsets: ["latin"],
});

export const metadata: Metadata = {
  title: "Civic City Hub — Local Government, Explained",
  description:
    "Making local government understandable. Plain-language summaries of city council agendas, budgets, and decisions for cities across America.",
  openGraph: {
    title: "Civic City Hub",
    description: "Plain-language summaries of city council agendas, budgets, and decisions.",
    type: "website",
  },
};

export default function RootLayout({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en" className={`${inter.variable} ${jetbrainsMono.variable}`} suppressHydrationWarning>
      <body className="min-h-screen antialiased">
        <Header />
        <main className="mx-auto px-4 py-6" style={{ maxWidth: "var(--max-width)" }}>
          {children}
        </main>
        <footer
          style={{
            borderTop: "1px solid var(--border)",
            marginTop: "3rem",
            padding: "2rem 1rem",
            textAlign: "center",
            fontSize: "0.8125rem",
            color: "var(--foreground-secondary)",
          }}
        >
          <div className="mx-auto px-4" style={{ maxWidth: "var(--max-width)" }}>
            <p className="font-semibold" style={{ fontFamily: "var(--font-serif)" }}>
              Civic City Hub
            </p>
            <p className="mt-1">
              Making local government understandable for everyone.
            </p>
            <p className="mt-3 text-xs">
              Data sourced from publicly available city council agendas.
              Not affiliated with any government entity.
            </p>
          </div>
        </footer>
      </body>
    </html>
  );
}
