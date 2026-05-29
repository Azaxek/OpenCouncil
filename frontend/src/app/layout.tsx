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
  title: "OpenCouncil — Local Government, Explained",
  description:
    "Making local government understandable. Plain-language summaries of city council minutes, budgets, and decisions for cities across America.",
  openGraph: {
    title: "OpenCouncil",
    description: "Plain-language summaries of city council minutes, budgets, and decisions.",
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
              OpenCouncil
            </p>
            <p className="mt-1">
              Making local government understandable for everyone.
            </p>
            <p className="mt-3 text-xs">
              Data sourced from publicly available city council minutes.
              Not affiliated with any government entity.
            </p>
            <div className="discrete-links mt-2">
              <a href="/about" className="text-gray-400 hover:text-gray-600 dark:hover:text-gray-300 text-sm mr-3">
                About
              </a>
              <a href="/contact" className="text-gray-400 hover:text-gray-600 dark:hover:text-gray-300 text-sm mr-3">
                Contact
              </a>
              <a
                href="/login"
                className="text-gray-400 hover:text-gray-600 dark:hover:text-gray-300"
                style={{ opacity: 0.3, fontSize: "0.7rem" }}
              >
                Volunteer Portal
              </a>
            </div>
          </div>
        </footer>
      </body>
    </html>
  );
}
