import { flag, fmt } from "../api";
import { LiveMsg, LiveState } from "../live";

/** Sixty one-second bars: routes opened (dark) with routes closed (red) stacked on top. Moves every second. */
export function Pulse({ live, dark = false }: { live: LiveState; dark?: boolean }) {
  const W = 480, H = 110, n = 60, bw = W / n;
  const ticks = live.ticks.slice(-n);
  const max = Math.max(50, ...ticks.map((t) => t.opened + t.closed));
  const now = ticks[ticks.length - 1];
  const base = dark ? "#f2f4f5" : "var(--ink)";
  if (live.status === "down" || (live.status === "connecting" && ticks.length === 0))
    return <p className="note" style={dark ? { color: "#b9c1c8" } : undefined}>{live.status === "down" ? "The live stream is not reachable right now. The figures on this page still refresh every few seconds." : "Connecting to the live stream…"}</p>;
  if (!live.feedUp)
    return <p className="note" style={dark ? { color: "#b9c1c8" } : undefined}>The live feed is reconnecting to its source. It usually returns within a minute; the other figures on this page are unaffected.</p>;
  return (
    <div className="pulse">
      <div className="pulse-now" aria-live="off">
        <b>{now ? fmt(now.opened + now.closed) : "–"}</b>
        <span>routes changed in the last second<br />{now ? `${fmt(now.opened)} opened, ${fmt(now.closed)} closed` : " "}</span>
      </div>
      <svg viewBox={`0 0 ${W} ${H}`} className="chart" role="img" aria-label="Route changes per second over the last minute" preserveAspectRatio="none">
        {ticks.map((t, i) => {
          const x = (n - ticks.length + i) * bw, ho = (t.opened / max) * (H - 4), hc = (t.closed / max) * (H - 4);
          return (
            <g key={t.t}>
              <rect x={x + 1} y={H - ho} width={bw - 2} height={ho} fill={base} opacity={i === ticks.length - 1 ? 1 : 0.55} />
              {hc > 0 && <rect x={x + 1} y={H - ho - hc} width={bw - 2} height={hc} fill="var(--red)" />}
            </g>
          );
        })}
      </svg>
      <div className="pulse-axis"><span>60 seconds ago</span><span>now</span></div>
    </div>
  );
}

const who = (name: string | null | undefined, asn: number | null) => name ?? (asn ? `AS${asn}` : "an unnamed network");

function sentence(m: LiveMsg) {
  if (m.k === "close")
    return <><b className="closed">Closed</b> {m.n === 1 ? "a route" : `${m.n} routes`} ({m.p}{m.n > 1 ? " and others" : ""}), reported by {who(m.pn, m.peer)}</>;
  return <><b>Opened</b> {m.n === 1 ? "a route" : `${m.n} routes`} to {m.o ? <a href={`/network/${m.o}`}>{who(m.on, m.o)}</a> : "a network"} {flag(m.oc)} ({m.p}{m.n > 1 ? " and others" : ""})</>;
}

/**
 * The newest real route changes, in words: a few per second out of everything received.
 * The list always has the same number of one-line rows, so the page below it never moves.
 */
export function Wire({ live, empty, rows = 10 }: { live: LiveState; empty?: string; rows?: number }) {
  const down = live.status === "down" || !live.feedUp;
  const msgs = down ? [] : live.msgs.slice(0, rows);
  return (
    <ol className="wire" aria-live="off" style={{ height: rows * 40 }}>
      {msgs.length === 0 && <li className="idle">{down ? "The live stream is not reachable right now." : empty ?? "Waiting for the next route change…"}</li>}
      {msgs.map((m) => <li key={m.id}>{sentence(m)}</li>)}
    </ol>
  );
}
