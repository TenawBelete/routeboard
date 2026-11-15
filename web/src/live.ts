import { useEffect, useState } from "react";

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
export interface LiveState { status: "connecting" | "live" | "down"; feedUp: boolean; ticks: Tick[]; msgs: LiveMsg[]; recent: Recent[] }

const KEEP_TICKS = 60, KEEP_MSGS = 14;

class Stream {
  state: LiveState = { status: "connecting", feedUp: true, ticks: [], msgs: [], recent: [] };
  private subs = new Set<(s: LiveState) => void>();
  private es: EventSource | null = null;
  private closing: ReturnType<typeof setTimeout> | null = null;
  private seq = 0;
  constructor(private url: string, private scope: string | null) {}

  private set(patch: Partial<LiveState>) { this.state = { ...this.state, ...patch }; this.subs.forEach((f) => f(this.state)); }

  private open() {
    if (this.es || typeof EventSource === "undefined") { if (typeof EventSource === "undefined") this.set({ status: "down" }); return; }
    const es = (this.es = new EventSource(this.url));
    es.addEventListener("hello", (e) => {
      const h = JSON.parse((e as MessageEvent).data);
      this.set({ status: "live", feedUp: h.up !== false, ticks: (h.history as Tick[]).slice(-KEEP_TICKS), recent: (h.recent as Recent[] | undefined) ?? [] });
    });
    es.addEventListener("tick", (e) => {
      const t = JSON.parse((e as MessageEvent).data) as Tick;
      this.set({ status: "live", feedUp: t.up !== false, ticks: [...this.state.ticks, t].slice(-KEEP_TICKS) });
    });
    es.addEventListener("msg", (e) => {
      const m = { ...(JSON.parse((e as MessageEvent).data) as Omit<LiveMsg, "id">), id: ++this.seq };
      this.set({ msgs: [m, ...this.state.msgs].slice(0, KEEP_MSGS) });
    });
    // Up to 120 real paths a second. The maps listen for these and move a dot along each one.
    es.addEventListener("paths", (e) => {
      for (const [path, pc] of JSON.parse((e as MessageEvent).data) as [number[], (string | null)[]][])
        window.dispatchEvent(new CustomEvent<RoutePath>("routeboard:route", { detail: { path, pc, scope: this.scope } }));
    });
    es.onerror = () => this.set({ status: es.readyState === EventSource.CLOSED ? "down" : "connecting" });   // the browser retries by itself
  }

  subscribe(f: (s: LiveState) => void) {
    if (this.closing) { clearTimeout(this.closing); this.closing = null; }
    this.subs.add(f); this.open(); f(this.state);
    return () => {
      this.subs.delete(f);
      if (this.subs.size === 0) this.closing = setTimeout(() => { this.es?.close(); this.es = null; this.state = { status: "connecting", feedUp: true, ticks: [], msgs: [], recent: [] }; }, 4000);
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
