import { useEffect, useMemo, useRef, useState } from "react";
import { Edge, layout } from "./network";

interface Props {
  edges: Edge[];
  interactive?: boolean;          // hover + click
  labels?: number;                // how many of the biggest nodes get a name
  pulses?: number;                // moving dots (0 = static)
  offsetX?: number;               // 0..1, shifts the map right (hero keeps text clear)
  selected?: number | null;
  onSelect?: (asn: number | null) => void;
  showNames?: boolean;            // false for the placeholder topology
  names?: Record<number, string>; // display names by network number
  live?: boolean;                 // true: dots move only when a real route change crosses a link
}

/** The AS-level network drawn on a canvas, with route "pulses" travelling along links. */
export function NetworkCanvas({ edges, interactive = false, labels = 0, pulses = 40, offsetX = 0, selected = null, onSelect, showNames = true, names, live = false }: Props) {
  const ref = useRef<HTMLCanvasElement>(null);
  const [hover, setHover] = useState<number | null>(null);
  const [tip, setTip] = useState<{ x: number; y: number; text: string } | null>(null);
  const g = useMemo(() => layout(edges), [edges]);
  const namesRef = useRef(names); namesRef.current = names;
  const nameOf = (id: number) => namesRef.current?.[id] ?? `AS${id}`;
  const focus = hover ?? (selected != null ? g.nodes.findIndex((n) => n.id === selected) : null);
  const focusRef = useRef<number | null>(null);
  focusRef.current = focus != null && focus >= 0 ? focus : null;
  // The selected network (not a hover): the view flies to it and only route changes passing through it are drawn.
  const selIdx = selected != null ? g.nodes.findIndex((n) => n.id === selected) : -1;
  const selRef = useRef<{ idx: number; id: number } | null>(null);
  selRef.current = selIdx >= 0 ? { idx: selIdx, id: selected! } : null;

  useEffect(() => {
    const cv = ref.current!; const ctx = cv.getContext("2d")!;
    let W = 0, H = 0, raf = 0, alive = true;
    const still = matchMedia("(prefers-reduced-motion: reduce)").matches || pulses === 0;
    const maxW = Math.max(1, ...g.edges.map((e) => e.weight)), maxN = Math.max(1, ...g.nodes.map((n) => n.w));
    const big = [...g.nodes].sort((a, b) => b.w - a.w).slice(0, labels).map((n) => n.id);
    const bx = (x: number) => (offsetX + x * (1 - offsetX)) * (W - 56) + 28, by = (y: number) => y * (H - 56) + 28;
    // Camera: zoom k around a centre (in unzoomed pixels). It eases toward the selected network, or back to the whole map.
    const cam = { k: 1, x: 0, y: 0, ready: false };
    const camTarget = () => { const s = selRef.current; return s ? { k: 1.9, x: bx(g.nodes[s.idx].x), y: by(g.nodes[s.idx].y) } : { k: 1, x: W / 2, y: H / 2 }; };
    const px = (x: number) => (bx(x) - cam.x) * cam.k + W / 2, py = (y: number) => (by(y) - cam.y) * cam.k + H / 2;
    const rad = (n: { w: number }) => 2.2 + 7 * Math.sqrt(n.w / maxN);
    const dots = Array.from({ length: still || live ? 0 : pulses }, () => ({ e: 0, t: Math.random(), v: 0, rev: false }));
    const pick = () => {                      // heavier links carry more pulses
      let r = Math.random() * g.edges.reduce((s, e) => s + Math.sqrt(e.weight), 0);
      for (let i = 0; i < g.edges.length; i++) { r -= Math.sqrt(g.edges[i].weight); if (r <= 0) return i; }
      return 0;
    };
    dots.forEach((d) => { d.e = pick(); d.v = 0.004 + Math.random() * 0.006; });
    // Live mode: a real route change travels from the network that owns the addresses outward,
    // one link after another, along the links of its path that are on this map.
    const byPair = new Map<string, number>();
    g.edges.forEach((e, i) => byPair.set(`${g.nodes[e.a].id}-${g.nodes[e.b].id}`, i));
    const onRoute = (ev: Event) => {
      const detail = (ev as CustomEvent).detail as { path?: number[]; scope?: string | null } | undefined;
      const path = detail?.path;
      if (!path || path.length < 2 || (detail?.scope ?? null) !== null || dots.length > 420 || document.hidden) return;
      if (selRef.current && !path.includes(selRef.current.id)) return;      // focused: only changes that pass through the selected network
      let hop = 0;
      for (let i = path.length - 1; i > 0; i--) {             // from the origin toward the reporter
        const fwd = byPair.get(`${path[i - 1]}-${path[i]}`), back = byPair.get(`${path[i]}-${path[i - 1]}`);
        if (fwd != null) dots.push({ e: fwd, t: -hop++, v: 0.035, rev: true });
        else if (back != null) dots.push({ e: back, t: -hop++, v: 0.035, rev: false });
      }
    };
    if (live && !still) window.addEventListener("routeboard:route", onRoute);

    const resize = () => {
      const r = cv.getBoundingClientRect(), dpr = Math.min(2, devicePixelRatio || 1);
      W = r.width; H = r.height; cv.width = W * dpr; cv.height = H * dpr; ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      if (!cam.ready || still) { Object.assign(cam, camTarget()); cam.ready = true; }
      if (still) draw();
    };
    const draw = () => {
      const f = focusRef.current;
      if (still) Object.assign(cam, camTarget());
      ctx.clearRect(0, 0, W, H);
      for (const e of g.edges) {
        const a = g.nodes[e.a], b = g.nodes[e.b], on = f == null || e.a === f || e.b === f;
        ctx.strokeStyle = on ? `rgba(16,24,32,${f == null ? 0.10 + 0.40 * Math.sqrt(e.weight / maxW) : 0.85})` : "rgba(16,24,32,0.05)";
        ctx.lineWidth = on && f != null ? 1.6 : 0.6 + 1.6 * Math.sqrt(e.weight / maxW);
        ctx.beginPath(); ctx.moveTo(px(a.x), py(a.y)); ctx.lineTo(px(b.x), py(b.y)); ctx.stroke();
      }
      for (const d of dots) {
        const e = g.edges[d.e]; if (!e) continue;
        const a = g.nodes[e.a], b = g.nodes[e.b];
        if (d.t < 0) continue;                                  // waiting for the previous link of its path
        const u = d.rev ? 1 - d.t : d.t;
        const x = px(a.x) + (px(b.x) - px(a.x)) * u, y = py(a.y) + (py(b.y) - py(a.y)) * u;
        if (live) {                                             // light up the stretch of link already travelled
          const s0 = d.rev ? b : a;
          ctx.strokeStyle = "rgba(255,210,0,0.75)"; ctx.lineWidth = 3;
          ctx.beginPath(); ctx.moveTo(px(s0.x), py(s0.y)); ctx.lineTo(x, y); ctx.stroke();
        }
        ctx.fillStyle = live ? "#ffd200" : `rgba(11,78,162,${Math.sin(d.t * Math.PI)})`;
        ctx.beginPath(); ctx.arc(x, y, live ? 3.6 : 2.4, 0, 6.3); ctx.fill();
        if (live) { ctx.strokeStyle = "#101820"; ctx.lineWidth = 1.5; ctx.stroke(); }
      }
      const near = new Set<number>();
      if (f != null) g.edges.forEach((e) => { if (e.a === f) near.add(e.b); if (e.b === f) near.add(e.a); });
      g.nodes.forEach((n, i) => {
        const on = f == null || i === f || near.has(i);
        ctx.fillStyle = i === f ? "#ffd200" : on ? "#101820" : "rgba(16,24,32,0.15)";
        ctx.beginPath(); ctx.arc(px(n.x), py(n.y), rad(n), 0, 6.3); ctx.fill();
        ctx.strokeStyle = i === f ? "#101820" : "#ffffff"; ctx.lineWidth = i === f ? 2.5 : 1.5; ctx.stroke();
      });
      if (showNames) {
        ctx.font = '600 13px "Overpass", "Helvetica Neue", Arial, sans-serif'; ctx.textBaseline = "middle";
        const placed: number[][] = [];
        const order = g.nodes.map((n, i) => ({ n, i })).sort((a, b) => (b.i === f ? 1 : 0) - (a.i === f ? 1 : 0) || b.n.w - a.n.w);
        order.forEach(({ n, i }) => {
          if (!(big.includes(n.id) || i === f || (selRef.current && f === selRef.current.idx && near.has(i)))) return;
          const full = nameOf(n.id), label = full.length > 22 && i !== f ? full.slice(0, 20).trimEnd() + "…" : full, tw = ctx.measureText(label).width, y = py(n.y);
          const x = px(n.x) + rad(n) + 6 + tw > W - 6 ? px(n.x) - rad(n) - 6 - tw : px(n.x) + rad(n) + 6;   // flip near the right edge
          const box = [x - 4, y - 10, x + tw + 4, y + 10];
          if (i !== f && placed.some((b) => box[0] < b[2] && box[2] > b[0] && box[1] < b[3] && box[3] > b[1])) return;
          placed.push(box);
          ctx.lineWidth = 4; ctx.strokeStyle = "rgba(255,255,255,0.92)"; ctx.strokeText(label, x, y);
          ctx.fillStyle = "#101820"; ctx.fillText(label, x, y);
        });
      }
    };
    const tick = () => {
      if (!alive) return;
      const ct = camTarget();                                    // ease the camera a tenth of the way each frame
      cam.k += (ct.k - cam.k) * 0.1; cam.x += (ct.x - cam.x) * 0.1; cam.y += (ct.y - cam.y) * 0.1;
      for (let i = dots.length - 1; i >= 0; i--) {
        const d = dots[i];
        d.t += d.v;                                             // negative t = waiting for the earlier links of its path
        if (d.t >= 1) { if (live) dots.splice(i, 1); else { d.t = 0; d.e = pick(); } }
      }
      draw(); raf = requestAnimationFrame(tick);
    };
    const ro = new ResizeObserver(resize); ro.observe(cv); resize();
    if (!still) raf = requestAnimationFrame(tick);
    const redraw = () => { if (still) draw(); };
    cv.addEventListener("bgp:redraw", redraw);

    const at = (ev: MouseEvent) => {
      const r = cv.getBoundingClientRect(), mx = ev.clientX - r.left, my = ev.clientY - r.top;
      let best = -1, bd = 18 * 18;
      g.nodes.forEach((n, i) => { const d = (px(n.x) - mx) ** 2 + (py(n.y) - my) ** 2; if (d < bd) { bd = d; best = i; } });
      return { best, mx, my };
    };
    const move = (ev: MouseEvent) => {
      const { best } = at(ev);
      setHover(best >= 0 ? best : null);
      if (best >= 0) { const n = g.nodes[best]; setTip({ x: px(n.x), y: py(n.y) - rad(n), text: `${nameOf(n.id)}: ${n.deg} ${n.deg === 1 ? "link" : "links"} shown. Click to focus on it` }); } else setTip(null);
      cv.style.cursor = best >= 0 ? "pointer" : "default";
    };
    const leave = () => { setHover(null); setTip(null); };
    const click = (ev: MouseEvent) => { const { best } = at(ev); onSelect?.(best >= 0 ? g.nodes[best].id : null); };
    if (interactive) { cv.addEventListener("mousemove", move); cv.addEventListener("mouseleave", leave); cv.addEventListener("click", click); }
    return () => { alive = false; cancelAnimationFrame(raf); ro.disconnect(); window.removeEventListener("routeboard:route", onRoute); cv.removeEventListener("bgp:redraw", redraw);
      cv.removeEventListener("mousemove", move); cv.removeEventListener("mouseleave", leave); cv.removeEventListener("click", click); };
  }, [g, interactive, labels, pulses, offsetX, showNames, onSelect, live]);

  useEffect(() => { ref.current?.dispatchEvent(new Event("bgp:redraw")); }, [focus]);

  return (
    <>
      <canvas ref={ref} role="img" aria-label="Map of networks and the links between them" />
      {interactive && tip && <div className="tip" style={{ left: tip.x, top: tip.y }}>{tip.text}</div>}
    </>
  );
}
