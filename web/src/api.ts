import { useEffect, useState } from "react";
import { apiUrl } from "./config";
import { fromBundle, getBundle, markOffline, markOnline, serverGone } from "./offline";

export interface Kpi { window_start: string; announcements: number; withdrawals: number; total_updates: number; withdraw_rate: number; updated_at: string }
export interface Timeline { minutes: number; points: { window_start: string; announcements: number; withdrawals: number; total_updates: number; peak_withdrawals?: number }[] }
export interface Named { name?: string | null; country?: string | null }
export interface PeerRow extends Named { peer_asn: number; updates: number; withdrawals: number; withdraw_rate: number }
export interface OriginRow extends Named { origin_asn: number; announcements: number }
export interface Health { status: "ok" | "degraded" | "down"; freshness: { kpi_updated_age_seconds: number | null; graph_computed_at: string | null; model_trained_at: string | null } }
export interface GraphRun { run_id: number; computed_at: string; window_hours: number; n_nodes: number; n_edges: number; n_components: number; largest_component_share: number }
export interface GraphNode extends Named { asn: number; pagerank: number; in_degree: number; out_degree: number; hub_score: number; pagerank_rank: number; hub_rank: number }
export interface GraphEdge { src: number; dst: number; weight: number; src_name?: string | null; dst_name?: string | null }
export interface ModelRun { run_id: number; trained_at: string; model_type: string; label_rule: string; train_from: string; train_to: string; test_from: string; test_to: string; n_train: number; n_test: number; positive_rate: number; auc: number | null; precision_: number | null; recall: number | null; f1: number | null; baseline_auc: number | null; features: string[]; coefficients: Record<string, number> | null }
export interface Prediction extends Named { window_start: string; peer_asn: number; probability: number; predicted: boolean; actual: boolean | null }

export interface SearchHit extends Named { asn: number; pagerank_rank: number | null }
export interface Neighbour extends Named { asn: number; weight: number }
export interface Network extends Named {
  asn: number; handle: string | null; seen: boolean;
  graph: { pagerank: number; pagerank_rank: number; hub_score: number; n_nodes: number; computed_at: string; window_hours: number } | null;
  upstream: Neighbour[]; downstream: Neighbour[];
  activity: { window_start: string; announcements: number }[];
  announcements_last_hour: number; announcements_usual_per_hour: number; activity_ratio: number | null;
  peer: { updates: number; withdrawals: number } | null;
  risk: { probability: number; window_start: string; actual: boolean | null } | null;
}
export interface BriefItem { event_id?: number | null; kind: string; tone: "alert" | "watch" | "info"; at: string | null; asn: number | null; title: string; detail: string }
export interface Briefing {
  state: { level: "calm" | "normal" | "busy" | "turbulent"; label: string; ratio: number; recent_per_minute: number; usual_per_minute: number } | null;
  items: BriefItem[];
  countries: { country: string; announcements: number; networks: number; share: number }[];
}

export interface EventRow extends Named { id: number; kind: "burst" | "surge"; started_at: string; ended_at: string; severity: "alert" | "watch"; value: number; magnitude: number; asn: number | null; title: string; detail: string }
export interface EventDetail extends EventRow { series: { window_start: string; value: number }[]; reporters: ({ asn: number; withdrawals: number } & Named)[] }
export interface StatusReport { overall: "ok" | "late" | "stalled"; stages: { key: string; label: string; what: string; last: string | null; age_seconds: number | null; state: "ok" | "late" | "stalled" | "waiting"; extra: string | null }[] }

export interface CountryRow { country: string; networks: number; changes_last_hour: number }
export interface CountryShare { country: string; weight: number; share: number; networks: number }
export interface Country {
  country: string; seen: boolean; networks_total: number;
  networks: ({ asn: number; pagerank_rank: number; hub_score: number } & Named)[];
  upstream_countries: CountryShare[]; downstream_countries: CountryShare[];
  upstream_networks: ({ asn: number; weight: number; share: number } & Named)[];
  domestic_links: number; routes_observed: number; window_days: number; enough_data: boolean;
  dependence: { upstream_networks: number; upstream_countries: number; top_share: number | null; top_name: string | null; top_asn: number | null };
  activity: { window_start: string; announcements: number }[];
  changes_last_hour: number; changes_usual_per_hour: number; activity_ratio: number | null;
  events: EventRow[]; computed_at: string | null; window_hours: number | null;
}

export type State<T> =
  | { kind: "loading" }
  | { kind: "ok"; data: T; at: number; saved?: boolean }   // saved: from the offline copy, `at` = when it was saved
  | { kind: "empty"; message: string }      // API reachable, job has not produced data yet (404)
  | { kind: "error"; message: string };     // API unreachable or failing

/** Fetch `path` now and every `ms` milliseconds. Keeps the last good data on a failed refresh. */
export function usePoll<T>(path: string, ms = 15000): State<T> {
  const [state, setState] = useState<State<T>>({ kind: "loading" });
  useEffect(() => {
    let stop = false;
    let retries = 0;
    const load = async () => {
      try {
        const r = await fetch(apiUrl(path), { headers: { Accept: "application/json" } });
        if (stop) return;
        if (serverGone(r.status)) {
          await showSaved();
        } else if (r.status === 404) {
          const j = await r.json().catch(() => ({}));
          setState({ kind: "empty", message: j.detail ?? "no data yet" });
        } else if (!r.ok) {
          setState((s) => (s.kind === "ok" ? s : { kind: "error", message: `API answered ${r.status}` }));
        } else {
          setState({ kind: "ok", data: (await r.json()) as T, at: Date.now() });
          // Only a health or status check proves the server is back: other answers can be
          // older copies that Cloudflare's cache serves while the server is away.
          if (/^\/(health|api\/status)/.test(path)) markOnline();
        }
      } catch {
        if (!stop) await showSaved();
      }
    };
    // The server is not there: show the copy saved by the offline Worker, if there is one.
    const showSaved = async () => {
      // The status page and health checks always report the real state, never a saved copy.
      const live = /^\/(api\/status|health|live\/)/.test(path);
      if (live) { const b = await getBundle(); if (b) markOffline(b.saved_at); }
      const hit = live ? null : await fromBundle<T>(path);
      if (stop) return;
      if (hit) {
        markOffline(hit.savedAt);
        setState({ kind: "ok", data: hit.data, at: hit.savedAt * 1000, saved: true });
      } else {
        setState((s) => (s.kind === "ok" ? s : { kind: "error", message: "cannot reach the API" }));
        // Do not wait for the next regular refresh (up to minutes): try again shortly.
        if (!live && retries++ < 5) setTimeout(() => { if (!stop) void load(); }, 3000);
      }
    };
    setState({ kind: "loading" });
    load();
    const id = setInterval(load, ms);
    return () => { stop = true; clearInterval(id); };
  }, [path, ms]);
  return state;
}

export const fmt = (n: number | null | undefined, digits = 0) =>
  n == null ? "–" : n.toLocaleString("en-US", { maximumFractionDigits: digits, minimumFractionDigits: digits });
export const pct = (x: number | null | undefined, digits = 1) => (x == null ? "–" : `${(x * 100).toFixed(digits)}%`);

export function ago(iso: string | null | undefined): string {
  if (!iso) return "never";
  const s = Math.max(0, (Date.now() - new Date(iso).getTime()) / 1000);
  if (s < 90) return `${Math.round(s)} s ago`;
  if (s < 5400) return `${Math.round(s / 60)} min ago`;
  if (s < 172800) return `${Math.round(s / 3600)} h ago`;
  return `${Math.round(s / 86400)} d ago`;
}

const regions = typeof Intl !== "undefined" && "DisplayNames" in Intl ? new Intl.DisplayNames(["en"], { type: "region" }) : null;
export function countryName(cc?: string | null): string {
  if (!cc) return "";
  try { return regions?.of(cc) ?? cc; } catch { return cc; }
}
export const flag = (cc?: string | null) =>
  cc && /^[A-Z]{2}$/.test(cc) ? String.fromCodePoint(...[...cc].map((c) => 0x1f1e6 + c.charCodeAt(0) - 65)) : "";
export const ordinal = (n: number) => {
  const s = ["th", "st", "nd", "rd"], v = n % 100;
  return n.toLocaleString("en-US") + (s[(v - 20) % 10] ?? s[v] ?? s[0]);
};
