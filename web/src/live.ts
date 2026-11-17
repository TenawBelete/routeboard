import { useEffect, useState } from "react";
import { apiUrl } from "./config";
import { getBundle, markOffline, markOnline } from "./offline";

// Client for the live service (Server-Sent Events). One shared connection per
// stream URL, opened when the first component needs it and closed shortly after
// the last one leaves, so moving between pages does not reconnect.

export interface Tick { t: number; opened: number; closed: number; messages: number; up?: boolean }
export interface LiveMsg {
  id: number; k: "open" | "close"; n: number; p: string;
  o: number | null; on: string | null; oc: string | null;
  path: number[]; pc: (string | null)[]; peer: number; pn?: string | null;
}
/** One real route change reduced to what the maps need: the networks on its path and their countries. */
export interface RoutePath { path: number[]; pc: (string | null)[]; scope: string | null; replay?: boolean }
export interface Recent { t: number; path: number[]; pc: (string | null)[] }
/** "replay": the server is unreachable and the 10 minutes saved before it stopped are being played back. */
export interface LiveState { status: "connecting" | "live" | "down" | "replay"; feedUp: boolean; ticks: Tick[]; msgs: LiveMsg[]; recent: Recent[]; savedAt?: number }

const KEEP_TICKS = 60, KEEP_MSGS = 14;
const STALL_MS = 6000;   // no event for this long = a proxy is holding the event stream back
const POLL_MS = 1000;    // fallback: one short request a second, which proxies do not hold back
const FAILS_BEFORE_REPLAY = 3;   // polls in a row that fail before the saved replay starts
const PROBE_MS = 10_000;         // while replaying, check this often whether the server is back

interface Snapshot {
  seq: number; up?: boolean; ticks: Tick[];
  paths: { s: number; path: number[]; pc: (string | null)[] }[];
  msgs: { s: number; k: "open" | "close"; n: number; p: string; o: number | null; on: string | null; oc: string | null; path: number[]; pc: (string | null)[]; peer: number; pn?: string | null }[];
  recent?: Recent[];
}

class Stream {
  state: LiveState = { status: "connecting", feedUp: true, ticks: [], msgs: [], recent: [] };
  private subs = new Set<(s: LiveState) => void>();
  private es: EventSource | null = null;
  private closing: ReturnType<typeof setTimeout> | null = null;
  private seq = 0;
  private mode: "sse" | "poll" | "replay" = "sse";
  private failures = 0;
  private replayTimer: ReturnType<typeof setInterval> | null = null;
  private probeTimer: ReturnType<typeof setInterval> | null = null;
  private lastEvent = 0;
  private watch: ReturnType<typeof setInterval> | null = null;
  private pollTimer: ReturnType<typeof setInterval> | null = null;
  private pollBusy = false;
  private after = 0;      // server sequence number already shown (polling)
  private lastTick = 0;   // newest tick second already shown (polling)
  constructor(private url: string, private scope: string | null) {}

  private set(patch: Partial<LiveState>) { this.state = { ...this.state, ...patch }; this.subs.forEach((f) => f(this.state)); }

  private open() {
    if (this.mode === "poll") { this.startPoll(); return; }
    if (this.es || typeof EventSource === "undefined") { if (typeof EventSource === "undefined") this.set({ status: "down" }); return; }
    this.lastEvent = Date.now();
    const es = (this.es = new EventSource(apiUrl(this.url)));
    es.addEventListener("hello", (e) => {
      this.lastEvent = Date.now();
      const h = JSON.parse((e as MessageEvent).data);
      this.set({ status: "live", feedUp: h.up !== false, ticks: (h.history as Tick[]).slice(-KEEP_TICKS), recent: (h.recent as Recent[] | undefined) ?? [] });
    });
    es.addEventListener("tick", (e) => {
      this.lastEvent = Date.now();
      const t = JSON.parse((e as MessageEvent).data) as Tick;
      this.set({ status: "live", feedUp: t.up !== false, ticks: [...this.state.ticks, t].slice(-KEEP_TICKS) });
    });
    es.addEventListener("msg", (e) => {
      this.lastEvent = Date.now();
      const m = { ...(JSON.parse((e as MessageEvent).data) as Omit<LiveMsg, "id">), id: ++this.seq };
      this.set({ msgs: [m, ...this.state.msgs].slice(0, KEEP_MSGS) });
    });
    // Up to 120 real paths a second. The maps listen for these and move a dot along each one.
    es.addEventListener("paths", (e) => {
      this.lastEvent = Date.now();
      for (const [path, pc] of JSON.parse((e as MessageEvent).data) as [number[], (string | null)[]][])
        window.dispatchEvent(new CustomEvent<RoutePath>("routeboard:route", { detail: { path, pc, scope: this.scope } }));
    });
    es.onerror = () => this.set({ status: es.readyState === EventSource.CLOSED ? "down" : "connecting" });   // the browser retries by itself
    if (!this.watch) this.watch = setInterval(() => this.checkStall(), 1000);
  }

  private checkStall() {
    if (this.mode === "sse" && Date.now() - this.lastEvent > STALL_MS) {
      this.es?.close(); this.es = null;
      this.mode = "poll"; this.after = 0;
      this.set({ status: "connecting" });
      this.startPoll();
    }
  }

  private startPoll() {
    if (this.pollTimer) return;
    this.pollTimer = setInterval(() => void this.poll(), POLL_MS);
    void this.poll();
  }

  private async poll() {
    if (this.pollBusy) return;
    this.pollBusy = true;
    try {
      const q = new URLSearchParams({ after: String(this.after) });
      if (this.scope) q.set("country", this.scope);
      if (this.after === 0 && this.scope) q.set("recent", "true");
      const r = await fetch(apiUrl(`/live/snapshot?${q}`), { cache: "no-store" });
      if (!r.ok) throw new Error(String(r.status));
      const j = (await r.json()) as Snapshot;
      const newTicks = j.ticks.filter((t) => t.t > this.lastTick);
      if (newTicks.length) this.lastTick = newTicks[newTicks.length - 1].t;
      const fresh: LiveMsg[] = j.msgs.map((m) => ({ id: m.s, k: m.k, n: m.n, p: m.p, o: m.o, on: m.on, oc: m.oc, path: m.path, pc: m.pc, peer: m.peer, pn: m.pn }));
      for (const p of j.paths)
        window.dispatchEvent(new CustomEvent<RoutePath>("routeboard:route", { detail: { path: p.path, pc: p.pc, scope: this.scope } }));
      this.after = Math.max(this.after, j.seq);
      this.failures = 0;
      markOnline();
      this.set({
        status: "live",
        feedUp: j.up !== false,
        ticks: [...this.state.ticks, ...newTicks].slice(-KEEP_TICKS),
        msgs: [...fresh.reverse(), ...this.state.msgs].slice(0, KEEP_MSGS),
        ...(j.recent ? { recent: j.recent } : {}),
      });
    } catch {
      if (++this.failures >= FAILS_BEFORE_REPLAY) void this.enterReplay();
      else this.set({ status: "connecting" });   // keeps trying every second
    } finally {
      this.pollBusy = false;
    }
  }

  /** The server is gone: play back the 10 minutes saved before it stopped, on a loop, until it returns. */
  private async enterReplay() {
    if (this.mode === "replay") return;
    this.mode = "replay";
    this.es?.close(); this.es = null;
    if (this.pollTimer) { clearInterval(this.pollTimer); this.pollTimer = null; }
    this.probeTimer = setInterval(() => void this.probe(), PROBE_MS);
    const b = await getBundle();
    if (this.mode !== "replay") return;
    const r = b?.replay;
    if (!b || !r || r.ticks.length === 0) { this.set({ status: "down" }); return; }
    markOffline(b.saved_at);
    const scope = this.scope;
    const paths = scope ? r.paths.filter((p) => p.pc.includes(scope)) : r.paths;
    const t0 = r.ticks[0].t, tEnd = r.ticks[r.ticks.length - 1].t + 1;
    let start = Date.now(), ti = 0, pi = 0;
    this.set({ status: "replay", savedAt: b.saved_at, feedUp: true, ticks: [], msgs: [], recent: scope ? r.recent[scope] ?? [] : [] });
    this.replayTimer = setInterval(() => {
      let cur = t0 + (Date.now() - start) / 1000;
      if (cur > tEnd) { start = Date.now(); ti = 0; pi = 0; cur = t0; this.set({ ticks: [] }); }   // loop from the start
      const fresh: Tick[] = [];
      while (ti < r.ticks.length && r.ticks[ti].t <= cur) fresh.push(r.ticks[ti++]);
      while (pi < paths.length && paths[pi].t <= cur) {
        const p = paths[pi++];
        if (!document.hidden) window.dispatchEvent(new CustomEvent<RoutePath>("routeboard:route", { detail: { path: p.path, pc: p.pc, scope, replay: true } }));
      }
      if (fresh.length) this.set({ ticks: [...this.state.ticks, ...fresh].slice(-KEEP_TICKS) });
    }, 250);
  }

  private async probe() {
    try {
      const q = new URLSearchParams({ after: "0" });
      if (this.scope) q.set("country", this.scope);
      const r = await fetch(apiUrl(`/live/snapshot?${q}`), { cache: "no-store" });
      if (r.ok) this.leaveReplay();
    } catch { /* still away */ }
  }

  private leaveReplay() {
    if (this.replayTimer) { clearInterval(this.replayTimer); this.replayTimer = null; }
    if (this.probeTimer) { clearInterval(this.probeTimer); this.probeTimer = null; }
    this.mode = "poll"; this.after = 0; this.lastTick = 0; this.failures = 0;
    markOnline();
    this.set({ status: "connecting", ticks: [], savedAt: undefined });
    this.startPoll();
  }

  private shutdown() {
    if (this.replayTimer) { clearInterval(this.replayTimer); this.replayTimer = null; }
    if (this.probeTimer) { clearInterval(this.probeTimer); this.probeTimer = null; }
    this.failures = 0;
    this.es?.close(); this.es = null;
    if (this.watch) { clearInterval(this.watch); this.watch = null; }
    if (this.pollTimer) { clearInterval(this.pollTimer); this.pollTimer = null; }
    this.mode = "sse"; this.after = 0; this.lastTick = 0;
    this.state = { status: "connecting", feedUp: true, ticks: [], msgs: [], recent: [] };
  }

  subscribe(f: (s: LiveState) => void) {
    if (this.closing) { clearTimeout(this.closing); this.closing = null; }
    this.subs.add(f); this.open(); f(this.state);
    return () => {
      this.subs.delete(f);
      if (this.subs.size === 0) this.closing = setTimeout(() => this.shutdown(), 4000);
    };
  }
}

const streams = new Map<string, Stream>();

/** Live route changes for the whole internet, or only those touching one country. */
export function useLive(country?: string | null): LiveState {
  const url = country ? `/live/stream?country=${country}` : "/live/stream";
  const [state, setState] = useState<LiveState>({ status: "connecting", feedUp: true, ticks: [], msgs: [], recent: [] });
  useEffect(() => {
    let s = streams.get(url);
    if (!s) streams.set(url, (s = new Stream(url, country ?? null)));
    return s.subscribe(setState);
  }, [url]);
  return state;
}
