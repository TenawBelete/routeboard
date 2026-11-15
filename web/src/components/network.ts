// Small force-directed layout + names for well-known networks. No dependencies.
export interface Edge { src: number; dst: number; weight: number }
export interface Node { id: number; x: number; y: number; deg: number; w: number }
export interface Layout { nodes: Node[]; edges: { a: number; b: number; weight: number }[] }

/** Deterministic pseudo-random so the same data always draws the same map. */
function rng(seed: number) { let s = seed >>> 0; return () => ((s = (s * 1664525 + 1013904223) >>> 0) / 4294967296); }

export function layout(edges: Edge[], aspect = 1.6, iterations = 260): Layout {
  const idx = new Map<number, number>();
  const nodes: Node[] = [];
  const get = (id: number) => { let i = idx.get(id); if (i == null) { i = nodes.length; idx.set(id, i); nodes.push({ id, x: 0, y: 0, deg: 0, w: 0 }); } return i; };
  const es = edges.filter((e) => e.src !== e.dst).map((e) => ({ a: get(e.src), b: get(e.dst), weight: e.weight }));
  es.forEach((e) => { nodes[e.a].deg++; nodes[e.b].deg++; nodes[e.a].w += e.weight; nodes[e.b].w += e.weight; });
  const n = nodes.length; if (!n) return { nodes, edges: es };
  const r = rng(n * 7919 + es.length);
  nodes.forEach((p) => { p.x = (r() - .5) * aspect; p.y = r() - .5; });
  const k = Math.sqrt(aspect / n) * 0.9;
  const dx = new Float64Array(n), dy = new Float64Array(n);
  for (let it = 0; it < iterations; it++) {
    const temp = 0.12 * (1 - it / iterations) + 0.004;
    dx.fill(0); dy.fill(0);
    for (let i = 0; i < n; i++) for (let j = i + 1; j < n; j++) {
      let ux = nodes[i].x - nodes[j].x, uy = nodes[i].y - nodes[j].y;
      const d2 = ux * ux + uy * uy + 1e-6, f = (k * k) / d2;
      ux *= f; uy *= f; dx[i] += ux; dy[i] += uy; dx[j] -= ux; dy[j] -= uy;
    }
    for (const e of es) {
      const ux = nodes[e.a].x - nodes[e.b].x, uy = nodes[e.a].y - nodes[e.b].y;
      const d = Math.sqrt(ux * ux + uy * uy) + 1e-6, f = (d * d) / k / d * 0.5;
      dx[e.a] -= ux * f; dy[e.a] -= uy * f; dx[e.b] += ux * f; dy[e.b] += uy * f;
    }
    for (let i = 0; i < n; i++) {
      dx[i] -= nodes[i].x * 0.6 / aspect; dy[i] -= nodes[i].y * 0.6;       // gravity to centre
      const d = Math.sqrt(dx[i] * dx[i] + dy[i] * dy[i]) + 1e-9, m = Math.min(d, temp);
      nodes[i].x += (dx[i] / d) * m; nodes[i].y += (dy[i] / d) * m;
    }
  }
  // Spread the crowded centre: the important networks all pull together, so distances from the
  // middle are stretched (radius^0.55). Order and neighbourhoods are kept; only the scale changes.
  const sx = [...nodes].map((p) => p.x).sort((a, b) => a - b), sy = [...nodes].map((p) => p.y).sort((a, b) => a - b);
  const mx = sx[n >> 1], my = sy[n >> 1];
  const rmax = Math.max(1e-9, ...nodes.map((p) => Math.hypot((p.x - mx) / aspect, p.y - my)));
  nodes.forEach((p) => {
    const dx0 = (p.x - mx) / aspect, dy0 = p.y - my, r = Math.hypot(dx0, dy0);
    if (r > 0) { const k2 = (rmax * Math.pow(r / rmax, 0.55)) / r; p.x = mx + dx0 * k2 * aspect; p.y = my + dy0 * k2; }
  });
  // normalise into [0,1] x [0,1]
  const xs = nodes.map((p) => p.x), ys = nodes.map((p) => p.y);
  const x0 = Math.min(...xs), x1 = Math.max(...xs), y0 = Math.min(...ys), y1 = Math.max(...ys);
  nodes.forEach((p) => { p.x = (p.x - x0) / (x1 - x0 || 1); p.y = (p.y - y0) / (y1 - y0 || 1); });
  return { nodes, edges: es };
}

/** Stand-in topology used only until the real graph has been computed. */
export function placeholderEdges(n = 70): Edge[] {
  const r = rng(42), out: Edge[] = [], ends: number[] = [1, 2];
  out.push({ src: 1, dst: 2, weight: 50 });
  for (let i = 3; i <= n; i++) for (let m = 0; m < (r() < 0.45 ? 2 : 1); m++) {
    const t = ends[Math.floor(r() * ends.length)];
    if (t !== i) { out.push({ src: i, dst: t, weight: 1 + Math.floor(r() * 40) }); ends.push(i, t); }
  }
  return out;
}
