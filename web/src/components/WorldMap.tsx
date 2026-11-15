import { memo, useEffect, useMemo, useRef, useState } from "react";
import { geoDistance, geoNaturalEarth1, geoPath } from "d3-geo";
import type { Feature, MultiPolygon } from "geojson";
import { countryName } from "../api";
import type { RoutePath } from "../live";

// Country shapes are a separate file (built by scripts/build-world.mjs from Natural Earth 1:50m,
// adjusted to UN-recognised borders) and are fetched once, only by pages that draw a map.
interface World { shapes: Feature<MultiPolygon>[]; centres: Record<string, [number, number]> }
let worldPromise: Promise<World> | null = null;
const loadWorld = () => (worldPromise ??= fetch("/world.json").then((r) => { if (!r.ok) throw new Error(String(r.status)); return r.json() as Promise<World>; })
  .then((w) => ({ ...w, shapes: w.shapes.filter((s) => s.id !== "AQ") }))            // no networks in Antarctica
  .catch((e) => { worldPromise = null; throw e; }));

const EDGE = 26;
const NEAR = 0.5;        // radians (~3,200 km): when zoomed in, partners nearer than this are framed with the country
const SPEED = 240;       // map units per second for a moving dot
const FLY_MS = 1300;     // how long the map takes to fly to a country

export interface Partner { cc: string; share: number; label?: boolean }
type Pt = [number, number];
/** Screen position = k * (position on the world view) + (tx, ty). Zooming is this one transform. */
interface View { k: number; tx: number; ty: number }
const IDENTITY: View = { k: 1, tx: 0, ty: 0 };

interface Props {
  focus?: string;
  partners?: Partner[];
  /** false: the whole world. true: fly in to the focus country and its neighbours. Changing it animates. */
  zoomed?: boolean;
  shade?: Record<string, number>;
  onPick?: (cc: string) => void;
  /** Draw real route changes as moving dots: null = the whole internet, "ER" = changes touching that country. */
  flows?: string | null;
  width?: number; height?: number;
}

/** The country outlines. Drawn once; zooming only changes the transform on the group around them. */
const Shapes = memo(function Shapes({ items, focus, partners, shade, onPick }:
  { items: { cc: string; d: string }[]; focus?: string; partners: string; shade?: Record<string, number>; onPick?: (cc: string) => void }) {
  const set = new Set(partners ? partners.split(",") : []);
  const max = shade ? Math.max(1, ...Object.values(shade)) : 1;
  const fill = (cc: string) => {
    if (cc.startsWith("_")) return "#eceff1";                                  // disputed area: neutral
    if (cc === focus) return "var(--yellow)";
    if (set.has(cc)) return "#aab4bc";
    if (shade) { const v = shade[cc] ?? 0; return v > 0 ? `rgba(16,24,32,${0.12 + 0.7 * Math.sqrt(v / max)})` : "#e3e7ea"; }
    return "#dfe4e8";
  };
  return (
    <>
      {items.map(({ cc, d }) => {
        const real = !cc.startsWith("_");
        return <path key={cc} d={d} fill={fill(cc)} stroke={cc === focus ? "var(--ink)" : "#fff"} strokeWidth={cc === focus ? 1.5 : 0.5} strokeLinejoin="round" vectorEffect="non-scaling-stroke"
          className={onPick && real ? "pick" : undefined} onClick={onPick && real ? () => onPick(cc) : undefined}>{real && <title>{countryName(cc)}</title>}</path>;
      })}
    </>
  );
});

export function WorldMap({ focus, partners = [], zoomed = false, shade, onPick, flows, width: W = 960, height: H = 520 }: Props) {
  const [world, setWorld] = useState<World | null>(null);
  const [failed, setFailed] = useState(false);
  const [view, setView] = useState<View>(IDENTITY);
  const viewRef = useRef<View>(IDENTITY);
  const canvas = useRef<HTMLCanvasElement>(null);
  useEffect(() => { let on = true; loadWorld().then((w) => on && setWorld(w)).catch(() => on && setFailed(true)); return () => { on = false; }; }, []);

  // Everything is laid out once on the whole-world view.
  const base = useMemo(() => {
    if (!world) return null;
    const all = { type: "FeatureCollection" as const, features: world.shapes };
    const proj = geoNaturalEarth1().fitExtent([[8, 8], [W - 8, H - 8]], all);
    const path = geoPath(proj);
    const points: Record<string, Pt> = {};
    for (const [cc, c] of Object.entries(world.centres)) { const p = proj(c); if (p) points[cc] = p as Pt; }
    return { items: world.shapes.map((s) => ({ cc: String(s.id), d: path(s) ?? "" })), points, scale: proj.scale(), translate: proj.translate() as Pt,
             drawn: new Set(world.shapes.map((s) => String(s.id))) };
  }, [world, W, H]);

  const partnerKey = partners.map((p) => p.cc).join(",");
  // Where the view should be: the whole world, or framed on the focus country and its neighbours.
  const target = useMemo<View>(() => {
    if (!world || !base || !focus || !zoomed || !world.centres[focus]) return IDENTITY;
    const C = world.centres;
    const near = partners.filter((p) => C[p.cc] && p.cc !== focus && geoDistance(C[focus], C[p.cc]) <= NEAR);
    const shape = world.shapes.find((s) => s.id === focus);
    const pad: [Pt, Pt] = [[W * 0.2, H * 0.23], [W * 0.8, H * 0.77]];
    const frame = { type: "GeometryCollection" as const, geometries: [
      ...(shape ? [shape.geometry] : []),
      { type: "MultiPoint" as const, coordinates: [C[focus], ...near.map((p) => C[p.cc])] },
    ] };
    // The frame may widen to take in neighbours, but the country never shrinks below ~40% of its best size.
    const proj = geoNaturalEarth1();
    const alone = shape ? geoNaturalEarth1().fitExtent(pad, shape).scale() : base.scale * 3;
    proj.fitExtent(pad, frame);
    const s = Math.max(base.scale * 1.7, Math.min(alone, base.scale * 9) * 0.4, Math.min(proj.scale(), base.scale * 6, alone));
    const fitMid = proj.invert!([W / 2, H / 2])!, own = C[focus], lean = s > proj.scale() * 1.02 ? 0.75 : 0;
    const mid: Pt = [fitMid[0] + (own[0] - fitMid[0]) * lean, fitMid[1] + (own[1] - fitMid[1]) * lean];
    // Same projection, larger scale: on screen that is exactly "scale the world view by k around a point".
    const k = s / base.scale;
    const m = geoNaturalEarth1().scale(base.scale).translate(base.translate)(mid)!;
    return { k, tx: W / 2 - k * m[0], ty: H / 2 - k * m[1] };
  }, [world, base, focus, zoomed, partnerKey, W, H]);   // eslint-disable-line react-hooks/exhaustive-deps

  // Fly from the current view to the target: the centre moves in a straight line while the zoom eases.
  useEffect(() => {
    const from = viewRef.current;
    if (Math.abs(from.k - target.k) < 1e-3 && Math.abs(from.tx - target.tx) < 0.5 && Math.abs(from.ty - target.ty) < 0.5) return;
    if (matchMedia("(prefers-reduced-motion: reduce)").matches) { viewRef.current = target; setView(target); return; }
    const centre = (v: View): Pt => [(W / 2 - v.tx) / v.k, (H / 2 - v.ty) / v.k];
    const c0 = centre(from), c1 = centre(target), t0 = performance.now();
    let raf = 0;
    const step = (now: number) => {
      const u = Math.min(1, (now - t0) / FLY_MS), e = u < 0.5 ? 4 * u * u * u : 1 - Math.pow(-2 * u + 2, 3) / 2;
      const k = Math.exp(Math.log(from.k) + (Math.log(target.k) - Math.log(from.k)) * e);
      const cx = c0[0] + (c1[0] - c0[0]) * e, cy = c0[1] + (c1[1] - c0[1]) * e;
      const v = { k, tx: W / 2 - k * cx, ty: H / 2 - k * cy };
      viewRef.current = v; setView(v);
      if (u < 1) raf = requestAnimationFrame(step);
    };
    raf = requestAnimationFrame(step);
    return () => cancelAnimationFrame(raf);
  }, [target, W, H]);

  // Real route changes: each one becomes a dot that hops country to country along the route's own path,
  // starting at the network that made the change. Nothing is drawn unless a real change arrived.
  useEffect(() => {
    if (flows === undefined || !base) return;
    const cv = canvas.current; if (!cv) return;
    const ctx = cv.getContext("2d")!;
    const still = matchMedia("(prefers-reduced-motion: reduce)").matches;
    const hops: { pts: Pt[]; seg: number; t: number }[] = [];      // points are on the world view; the zoom is applied when drawing
    const rings: { p: Pt; t: number }[] = [];
    const onRoute = (ev: Event) => {
      const d = (ev as CustomEvent<RoutePath>).detail;
      if (!d || (d.scope ?? null) !== flows || document.hidden || hops.length > 260) return;
      const pts: Pt[] = []; let last = "";
      for (let i = d.pc.length - 1; i >= 0; i--) {                 // from the origin outward
        const cc = d.pc[i]; if (!cc || cc === last) continue;
        const p = base.points[cc]; if (!p) continue;
        pts.push(p); last = cc;
      }
      if (pts.length >= 2) hops.push({ pts, seg: 0, t: 0 });
      else if (pts.length === 1 && rings.length < 50) rings.push({ p: pts[0], t: 0 });   // a change that stayed inside one country
    };
    window.addEventListener("routeboard:route", onRoute);
    let raf = 0, prev = performance.now(), alive = true;
    const frame = (now: number) => {
      if (!alive) return;
      const dt = Math.min(0.1, (now - prev) / 1000); prev = now;
      const r = cv.getBoundingClientRect(), dpr = Math.min(2, devicePixelRatio || 1);
      if (cv.width !== Math.round(r.width * dpr)) { cv.width = Math.round(r.width * dpr); cv.height = Math.round(r.height * dpr); }
      const s = (r.width * dpr) / W, v = viewRef.current;
      const at = (p: Pt): Pt => [v.k * p[0] + v.tx, v.k * p[1] + v.ty];
      ctx.setTransform(s, 0, 0, s, 0, 0);
      ctx.clearRect(0, 0, W, H);
      for (let i = rings.length - 1; i >= 0; i--) {
        const g = rings[i]; g.t += dt / 0.7;
        if (g.t >= 1) { rings.splice(i, 1); continue; }
        const p = at(g.p);
        ctx.strokeStyle = `rgba(16,24,32,${0.6 * (1 - g.t)})`; ctx.lineWidth = 1.5;
        ctx.beginPath(); ctx.arc(p[0], p[1], 3 + 9 * g.t, 0, 6.3); ctx.stroke();
      }
      for (let i = hops.length - 1; i >= 0; i--) {
        const h = hops[i], a = at(h.pts[h.seg]), b = at(h.pts[h.seg + 1]);
        const len = Math.hypot(b[0] - a[0], b[1] - a[1]) || 1;
        h.t += (SPEED * Math.max(1, Math.sqrt(v.k)) * dt) / len;
        if (h.t >= 1) { h.seg++; h.t = 0; if (h.seg >= h.pts.length - 1) { hops.splice(i, 1); rings.push({ p: h.pts[h.pts.length - 1], t: 0.3 }); } continue; }
        const x = a[0] + (b[0] - a[0]) * h.t, y = a[1] + (b[1] - a[1]) * h.t;
        ctx.strokeStyle = "rgba(16,24,32,0.45)"; ctx.lineWidth = 1.2;      // the stretch already travelled
        ctx.beginPath(); ctx.moveTo(a[0], a[1]); ctx.lineTo(x, y); ctx.stroke();
        ctx.fillStyle = "#ffd200"; ctx.strokeStyle = "#101820"; ctx.lineWidth = 1.4;
        ctx.beginPath(); ctx.arc(x, y, 3.4, 0, 6.3); ctx.fill(); ctx.stroke();
      }
      raf = requestAnimationFrame(frame);
    };
    if (!still) raf = requestAnimationFrame(frame);
    return () => { alive = false; cancelAnimationFrame(raf); window.removeEventListener("routeboard:route", onRoute); };
  }, [flows, base, W]);

  if (failed) return <p className="note" style={{ padding: 16 }}>The map could not be loaded. The figures below are unaffected.</p>;
  if (!world || !base) return <div className="world-loading" style={{ aspectRatio: `${W} / ${H}` }} aria-busy="true">Loading the map…</div>;

  const pt = (cc: string): Pt | null => { const p = base.points[cc]; return p ? [view.k * p[0] + view.tx, view.k * p[1] + view.ty] : null; };
  const inFrame = (q: Pt) => q[0] > EDGE && q[0] < W - EDGE && q[1] > EDGE && q[1] < H - EDGE;
  const known = partners.filter((p) => base.points[p.cc] && p.cc !== focus);
  const f = focus ? pt(focus) : null;
  const wide = view.k < 1.3;                                                    // close to the whole-world view

  // One line per partner: a curve when the partner is on the map, a straight line to the edge when it is not.
  const lines = f ? known.map((p, i) => {
    const q = pt(p.cc); if (!q) return null;
    const far = !inFrame(q);
    let end = q;
    if (far) {
      let t = 1; const dx0 = q[0] - f[0], dy0 = q[1] - f[1];
      if (dx0 > 0) t = Math.min(t, (W - EDGE - f[0]) / dx0); else if (dx0 < 0) t = Math.min(t, (EDGE - f[0]) / dx0);
      if (dy0 > 0) t = Math.min(t, (H - EDGE - f[1]) / dy0); else if (dy0 < 0) t = Math.min(t, (EDGE - f[1]) / dy0);
      end = [f[0] + dx0 * t, f[1] + dy0 * t];
    }
    const dx = f[0] - end[0], dy = f[1] - end[1], len = Math.hypot(dx, dy) || 1;
    const bend = far ? 0 : Math.min(60, len * 0.18) * (i % 2 ? -1 : 1);
    const mx = (end[0] + f[0]) / 2 - (dy / len) * bend, my = (end[1] + f[1]) / 2 + (dx / len) * bend;
    return { p, far, end, len, ux: -dx / len, uy: -dy / len, d: `M${end[0].toFixed(1)},${end[1].toFixed(1)} Q${mx.toFixed(1)},${my.toFixed(1)} ${f[0].toFixed(1)},${f[1].toFixed(1)}` };
  }).filter((x): x is NonNullable<typeof x> => !!x) : [];

  const placed: number[][] = f ? [[f[0] - 62, f[1] + 12, f[0] + 62, f[1] + 32]] : [];
  // On the whole-world view, close neighbours sit on top of the country; their names appear once zoomed in.
  const labels = lines.filter(({ len }) => !wide || len > 48).map(({ p, far, end, ux, uy }) => {
    const text = (p.label === false ? countryName(p.cc) : `${countryName(p.cc)} ${Math.round(p.share * 100)}%`) + (far ? " (off map)" : "");
    const w = text.length * 7.3;
    let anchor: "start" | "middle" | "end" = ux > 0.35 ? "start" : ux < -0.35 ? "end" : "middle";
    let x = end[0] + ux * 12, y = end[1] + uy * 12 + (uy > 0 ? 12 : -4);
    if (far) { anchor = end[0] > W * 0.6 ? "end" : end[0] < W * 0.4 ? "start" : "middle"; x = Math.min(W - 10, Math.max(10, end[0])); y = Math.min(H - 10, Math.max(18, end[1] + (end[1] < H / 2 ? 16 : -8))); }
    if (anchor === "start" && x + w > W - 6) anchor = "end";                    // keep every label inside the frame
    if (anchor === "end" && x - w < 6) anchor = "start";
    const box = () => { const x0 = anchor === "start" ? x : anchor === "end" ? x - w : x - w / 2; return [x0, y - 13, x0 + w, y + 4]; };
    for (let n = 0; n < 12 && placed.some((o) => { const b = box(); return b[0] < o[2] && b[2] > o[0] && b[1] < o[3] && b[3] > o[1]; }); n++) y += (far ? end[1] < H / 2 : uy >= 0) ? 17 : -17;
    placed.push(box());
    return { cc: p.cc, text, x, y, anchor };
  });

  return (
    <div className="worldwrap">
      <svg viewBox={`0 0 ${W} ${H}`} className="world" role="img" aria-label={focus ? `Map of how ${countryName(focus)} connects to other countries` : "World map of network activity"}>
        <rect width={W} height={H} fill="#fff" />
        <g transform={`matrix(${view.k} 0 0 ${view.k} ${view.tx} ${view.ty})`}>
          <Shapes items={base.items} focus={focus} partners={known.map((p) => p.cc).join(",")} shade={shade} onPick={onPick} />
        </g>
        {lines.map(({ p, d }) => <path key={p.cc} d={d} fill="none" stroke="var(--ink)" strokeWidth={1.2 + 5 * p.share} strokeLinecap="round" opacity="0.8" />)}
        {f && known.filter((p) => !base.drawn.has(p.cc)).map((p) => { const q = pt(p.cc); return q && inFrame(q) ? <rect key={p.cc} x={q[0] - 4} y={q[1] - 4} width="8" height="8" fill="#aab4bc" stroke="var(--ink)" /> : null; })}
        {lines.map(({ p, end, far }) => far ? null : <circle key={`e-${p.cc}`} cx={end[0]} cy={end[1]} r="3.2" fill="var(--ink)" />)}
        {labels.map((l) => <text key={l.cc} x={l.x} y={l.y} textAnchor={l.anchor} className="lbl">{l.text}</text>)}
        {f && (
          <g>
            {!base.drawn.has(focus!) && <rect x={f[0] - 5} y={f[1] - 5} width="10" height="10" fill="var(--yellow)" stroke="var(--ink)" strokeWidth="1.5" />}
            {wide && <circle cx={f[0]} cy={f[1]} r="15" fill="none" stroke="var(--ink)" strokeWidth="2" />}
            <text x={f[0]} y={f[1] + (wide ? 32 : 26)} textAnchor="middle" className="lbl focus">{countryName(focus)}</text>
          </g>
        )}
      </svg>
      {flows !== undefined && <canvas ref={canvas} className="flows" aria-hidden="true" />}
    </div>
  );
}
