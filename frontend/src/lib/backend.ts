/**
 * Where the Python backend lives.
 *
 * NEXT_PUBLIC_API_URL overrides everything. On Vercel the default is the Hugging Face Space;
 * locally it is the dev server on port 8000.
 */
export const DEFAULT_SPACE_URL = "https://comfoa-civilly-simplified-backend.hf.space";

export function getBackendUrl(): string {
  if (process.env.NEXT_PUBLIC_API_URL) return process.env.NEXT_PUBLIC_API_URL.trim();
  if (process.env.VERCEL) return DEFAULT_SPACE_URL;
  return "http://localhost:8000";
}
