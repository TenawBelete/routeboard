// Where the data comes from. Locally (Caddy serves everything) both are empty, so requests stay on
// the same origin. On Cloudflare Pages the build sets them:
//   VITE_API_BASE=https://api.butenai.com   the server on the Mac, through the Cloudflare tunnel
//   VITE_OFFLINE_URL=https://data.butenai.com/bundle.json   the copy saved by the offline Worker
export const API_BASE = String(import.meta.env.VITE_API_BASE ?? "").replace(/\/$/, "");
export const OFFLINE_URL = String(import.meta.env.VITE_OFFLINE_URL ?? "");
export const apiUrl = (path: string) => `${API_BASE}${path}`;
