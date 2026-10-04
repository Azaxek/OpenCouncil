// Pre-generated summaries of real Paris, TX council minutes (see data/sample-minutes.json).
// Static on purpose: no API, database or LLM call, so these pages always render the same way.
import raw from "@/data/sample-minutes.json";

export interface SampleMinutes {
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

export interface SampleSummary {
  big_picture: string;
  summary: string;
  key_decisions: Array<{ title: string; plain_english: string; impact: string; category: string }>;
  budget_items: Array<{ title: string; amount: string; description: string }>;
  public_comment_opportunities: Array<{ item: string; deadline: string; how: string }>;
  items: Array<{ title: string; plain_english: string; category: string; action_needed: string }>;
  what_you_can_do: Array<{ action: string; who: string }>;
}

export interface Sample {
  minutes: SampleMinutes;
  summary: SampleSummary;
}

export const SAMPLES = raw as Sample[];

export const findSample = (id: string): Sample | undefined =>
  SAMPLES.find((s) => s.minutes.id === id);
