import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { GraphEdge, fmt } from "../api";
import type { RoutePath } from "../live";
import { NetworkCanvas } from "./NetworkCanvas";

/**
 * The network map with selection. Clicking a network flies the view to it, lights up its connections,
 * shows only the real route changes that pass through it, and offers a link to its full page.
 */
export function NetworkMap({ edges, labels = 12, small = false, selected, onSelect }:
  { edges: GraphEdge[]; labels?: number; small?: boolean; selected?: number | null; onSelect?: (asn: number | null) => void }) {
  const [own, setOwn] = useState<number | null>(null);
  const sel = selected !== undefined ? selected : own;
  // A stable handler: the map component must not restart its animation every time this one re-renders.
  const latest = useRef({ sel, onSelect }); latest.current = { sel, onSelect };
  const choose = useCallback((asn: number | null) => { const { onSelect: cb } = latest.current; if (cb) cb(asn); else setOwn(asn); }, []);
  const toggle = useCallback((asn: number | null) => choose(asn === latest.current.sel ? null : asn), [choose]);
  const names = useMemo(() => {
    const m: Record<number, string> = {};
    edges.forEach((e) => { if (e.src_name) m[e.src] = e.src_name; if (e.dst_name) m[e.dst] = e.dst_name; });
    return m;
  }, [edges]);
  const links = useMemo(() => (sel == null ? 0 : edges.filter((e) => e.src === sel || e.dst === sel).length), [edges, sel]);

  // How many real route changes passed through the selected network in the last minute.
  const [through, setThrough] = useState(0);
  useEffect(() => {
    setThrough(0);
    if (sel == null) return;
    let times: number[] = [];
    const onRoute = (ev: Event) => { const d = (ev as CustomEvent<RoutePath>).detail; if (d.scope === null && d.path.includes(sel)) times.push(Date.now()); };
    window.addEventListener("routeboard:route", onRoute);
    const id = setInterval(() => { const cut = Date.now() - 60000; times = times.filter((t) => t >= cut); setThrough(times.length); }, 1000);
    return () => { clearInterval(id); window.removeEventListener("routeboard:route", onRoute); };
  }, [sel]);

  return (
    <div className={`mapbox ${small ? "small" : ""}`}>
      <NetworkCanvas edges={edges} names={names} interactive labels={labels} live selected={sel} onSelect={toggle} />
      {sel != null && (
        <div className="nodecard" role="status">
          <b>{names[sel] ?? `Network ${sel}`}</b>
          <span>{links} {links === 1 ? "connection" : "connections"} on this map. {fmt(through)} real route {through === 1 ? "change" : "changes"} passed through it in the last minute; only those are shown now.</span>
          <div><a className="btn" href={`/network/${sel}`}>Open details</a><button className="btn" onClick={() => choose(null)}>Show whole map</button></div>
        </div>
      )}
    </div>
  );
}
