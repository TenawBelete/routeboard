import { useRef, useState } from "react";

export interface Point { t: number; v: number }

/** Dependency-free SVG line/area chart with a hover crosshair and tooltip. */
export function LineChart({ points, color, label, unit = "", height = 220, bare = false, band }:
  { points: Point[]; color: string; label: string; unit?: string; height?: number; bare?: boolean; band?: [number, number] }) {
  const W = 720, H = height, L = bare ? 8 : 52, R = 10, T = 12, B = bare ? 8 : 26;
  const ref = useRef<HTMLDivElement>(null);
  const [hover, setHover] = useState<number | null>(null);

  if (points.length < 2) return <div className="empty">Not enough points yet.</div>;

  const t0 = points[0].t, t1 = points[points.length - 1].t;
  const max = Math.max(1, ...points.map((p) => p.v)) * 1.1;
  const x = (t: number) => L + ((t - t0) / Math.max(1, t1 - t0)) * (W - L - R);
  const y = (v: number) => T + (1 - v / max) * (H - T - B);
  const line = points.map((p, i) => `${i ? "L" : "M"}${x(p.t).toFixed(1)},${y(p.v).toFixed(1)}`).join(" ");
  const area = `${line} L${x(t1).toFixed(1)},${H - B} L${x(t0).toFixed(1)},${H - B} Z`;
  const ticks = [0, 0.5, 1].map((f) => f * max);
  const long = t1 - t0 > 36 * 3600 * 1000;
  const hh = (t: number) => long ? new Date(t).toISOString().slice(5, 16).replace("T", " ") : new Date(t).toISOString().slice(11, 16);

  const onMove = (e: React.MouseEvent) => {
    const r = ref.current!.getBoundingClientRect();
    const px = ((e.clientX - r.left) / r.width) * W;
    let best = 0, bd = Infinity;
    points.forEach((p, i) => { const d = Math.abs(x(p.t) - px); if (d < bd) { bd = d; best = i; } });
    setHover(best);
  };
  const hp = hover != null ? points[hover] : null;

  return (
    <div className="relative" ref={ref} onMouseMove={bare ? undefined : onMove} onMouseLeave={() => setHover(null)}>
      <svg className="chart" preserveAspectRatio={bare ? "none" : undefined} viewBox={`0 0 ${W} ${H}`} role="img" aria-label={`${label} over time`}>
        {!bare && ticks.map((tv) => (
          <g key={tv}>
            <line x1={L} x2={W - R} y1={y(tv)} y2={y(tv)} stroke="var(--rule)" strokeWidth="1" />
            <text x={L - 6} y={y(tv) + 4} textAnchor="end">{tv >= 1000 ? `${(tv / 1000).toFixed(1)}k` : Math.round(tv)}</text>
          </g>
        ))}
        {band && <rect x={x(Math.max(t0, band[0]))} y={T} width={Math.max(3, x(Math.min(t1, band[1])) - x(Math.max(t0, band[0])))} height={H - T - B} fill="var(--red)" opacity="0.16" />}
        <path d={area} fill={color} opacity="0.14" />
        <path d={line} fill="none" stroke={color} strokeWidth="2" strokeLinejoin="round" />
        {!bare && <text x={L} y={H - 6}>{hh(t0)} UTC</text>}
        {!bare && <text x={W - R} y={H - 6} textAnchor="end">{hh(t1)} UTC</text>}
        {hp && (
          <g>
            <line x1={x(hp.t)} x2={x(hp.t)} y1={T} y2={H - B} stroke="var(--dim)" strokeDasharray="3 3" />
            <circle cx={x(hp.t)} cy={y(hp.v)} r="4.5" fill={color} stroke="var(--panel)" strokeWidth="2" />
          </g>
        )}
      </svg>
      {hp && (
        <div className="tip" style={{ left: `${(x(hp.t) / W) * 100}%`, top: `${(y(hp.v) / H) * 100}%` }}>
          <b>{hp.v.toLocaleString("en-US")}</b> {unit} at {hh(hp.t)} UTC
        </div>
      )}
    </div>
  );
}
