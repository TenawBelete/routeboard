import { useSyncExternalStore } from "react";
import { OFFLINE_URL } from "./config";
import type { Recent, Tick } from "./live";

// Offline mode. When the server stops, the pages show the copy a Cloudflare Worker saved a few
// minutes earlier, and the live views replay the 10 minutes before it. A banner says so plainly;
// nothing is presented as live that is not.

export interface ReplayPath { t: number; path: number[]; pc: (string | null)[] }
export interface Replay { saved_at: number; seconds: number; ticks: Tick[]; paths: ReplayPath[]; recent: Record<string, Recent[]> }
export interface Bundle { version: number; saved_at: number; api: Record<string, unknown>; replay: Replay | null }

let bundle: Promise<Bundle | null> | null = null;
let fetchedAt = 0;

/** The saved copy, fetched at most once a minute. Null when offline mode is not set up or nothing is saved. */
export function getBundle(): Promise<Bundle | null> {
  if (!OFFLINE_URL) return Promise.resolve(null);
  if (!bundle || Date.now() - fetchedAt > 60_000) {
    fetchedAt = Date.now();
    bundle = fetch(OFFLINE_URL, { cache: "no-store" })
      .then((r) => (r.ok ? (r.json() as Promise<Bundle>) : null))
      .catch(() => null)
      .then((b) => { if (!b) fetchedAt = 0; return b; });   // a failed fetch is retried next time, not remembered for a minute
  }
  return bundle;
}

/** The saved answer for an API path: exact match first, then the same path with other parameters. */
export async function fromBundle<T>(path: string): Promise<{ data: T; savedAt: number } | null> {
  const b = await getBundle();
  if (!b?.api) return null;
  if (path in b.api) return { data: b.api[path] as T, savedAt: b.saved_at };
  const bare = path.split("?")[0];
  const key = Object.keys(b.api).find((k) => k.split("?")[0] === bare);
  return key ? { data: b.api[key] as T, savedAt: b.saved_at } : null;
}

/** Answers that mean "the server is not there" (as opposed to a bug): network errors and gateway codes. */
export const serverGone = (status: number) => status === 502 || status === 503 || status === 504 || (status >= 520 && status <= 530);

// Shared "are we offline" flag for the banner and the status light.
let savedAt: number | null = null;
const subs = new Set<() => void>();
const emit = () => subs.forEach((f) => f());
export function markOffline(at: number) { if (savedAt !== at) { savedAt = at; emit(); } }
export function markOnline() { if (savedAt !== null) { savedAt = null; emit(); } }
export function useOffline(): number | null {
  return useSyncExternalStore((f) => { subs.add(f); return () => subs.delete(f); }, () => savedAt, () => null);
}
