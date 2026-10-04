import Link from "next/link";
import { SAMPLES } from "@/lib/samples";

const formatDate = (d: string) =>
  new Date(d).toLocaleDateString("en-US", { weekday: "long", year: "numeric", month: "long", day: "numeric", timeZone: "America/Chicago" });

export default function SamplesPage() {
  return (
    <div className="space-y-8">
      <div>
        <h1 className="news-headline-xl" style={{ marginBottom: "0.5rem" }}>Sample Summaries</h1>
        <p className="news-body" style={{ fontSize: "1rem" }}>
          Plain-language summaries of real Paris, Texas city council meetings. These are pre-generated
          from the official minutes and stored with the site, so they load instantly and never change
          between visits. Every summary links back to the original document.
        </p>
      </div>

      <hr className="news-divider" />

      <div className="space-y-3">
        {SAMPLES.map(({ minutes }, index) => (
          <Link key={minutes.id} href={`/minutes/${minutes.id}`} style={{ textDecoration: "none" }}>
            <article className={`article-card ${index === 0 ? "article-card-featured" : ""}`} style={{ padding: "1.25rem" }}>
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", gap: "1rem" }}>
                <div style={{ flex: 1, minWidth: 0 }}>
                  <div style={{ display: "flex", gap: "0.5rem", marginBottom: "0.25rem" }}>
                    <span className="badge badge-green" style={{ fontSize: "0.625rem" }}>Summarized</span>
                    <span className="badge badge-brand" style={{ fontSize: "0.625rem" }}>{minutes.meeting_type}</span>
                  </div>
                  <h3 className="news-headline-md" style={{ fontSize: "1.1rem" }}>{minutes.title}</h3>
                  <p className="news-byline" style={{ marginTop: "0.25rem" }}>{formatDate(minutes.meeting_date)}</p>
                </div>
                <span style={{ color: "var(--foreground-secondary)", fontSize: "1.25rem" }}>→</span>
              </div>
            </article>
          </Link>
        ))}
      </div>
    </div>
  );
}
