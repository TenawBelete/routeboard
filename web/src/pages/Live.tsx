import { useState } from "react";
import { Kpi, OriginRow, PeerRow, Timeline, ago, fmt, pct, usePoll } from "../api";
import { LineChart } from "../components/LineChart";
import { Async, Meter, Net, Seg } from "../components/ui";
import { Pulse } from "../components/Live";
import { useLive } from "../live";

const RANGES = [{ v: 60, l: "Last hour" }, { v: 360, l: "6 hours" }, { v: 1440, l: "24 hours" }, { v: 10080, l: "7 days" }];

export default function Live() {
  const [mins, setMins] = useState(60);
  const kpi = usePoll<Kpi>("/api/kpi/latest", 15000);
  const tl = usePoll<Timeline>(`/api/kpi/timeline?minutes=${mins}`, 30000);
  const peers = usePoll<{ items: PeerRow[] }>(`/api/peers/top?limit=10&window_minutes=${Math.min(mins, 1440)}`, 30000);
  const origins = usePoll<{ items: OriginRow[] }>(`/api/origins/top?limit=10&window_minutes=${Math.min(mins, 1440)}`, 30000);
  const live = useLive();
  const range = RANGES.find((r) => r.v === Math.min(mins, 1440))!.l.toLowerCase();
  const week = mins > 1440;

  return (
    <>
      <div className="band white">
        <div className="wrap split">
          <div>
            <h1>Traffic on the board</h1>
            <p className="lead">Routes open and close all day; that is the internet healing and rebalancing itself. What matters is the balance between the two, and sudden jumps.</p>
          </div>
          <Async state={kpi} what="live numbers">
            {(k) => (
              <div>
                <div className="fact">{fmt(k.total_updates)}</div>
                <p className="note">route changes in the minute ending {k.window_start.slice(11, 16)} UTC, updated {ago(k.updated_at)}</p>
                <div className="ratio" role="img" aria-label={`${pct(1 - k.withdraw_rate)} opened, ${pct(k.withdraw_rate)} closed`}>
                  <i style={{ flex: k.announcements, background: "var(--ink)" }} /><i style={{ flex: Math.max(k.withdrawals, 1), background: "var(--red)" }} />
                </div>
                <div className="key">
                  <span><i style={{ background: "var(--ink)" }} />{fmt(k.announcements)} opened ({pct(1 - k.withdraw_rate)})</span>
                  <span><i style={{ background: "var(--red)" }} />{fmt(k.withdrawals)} closed ({pct(k.withdraw_rate)})</span>
                </div>
              </div>
            )}
          </Async>
        </div>
      </div>
      <div className="band">
        <div className="wrap" style={{ maxWidth: 860 }}>
          <h2>Second by second</h2>
          <p className="note" style={{ margin: "6px 0 14px" }}>Each bar is one second. Dark is routes opened, red is routes closed. It moves as the messages arrive.</p>
          <Pulse live={live} />
        </div>
      </div>
      <div className="band white">
        <div className="wrap">
          <div className="rowhead"><h2>Minute by minute</h2><Seg value={mins} options={RANGES} onChange={setMins} label="Time range" /></div>
          <Async state={tl} what="timeline">
            {(d) => {
              const pts = (f: "announcements" | "withdrawals") => d.points.map((p) => ({ t: Date.parse(p.window_start), v: p[f] }));
              return (
                <div className="split even">
                  <div><h3>Routes opened per minute{week ? ", hourly average" : ""}</h3><LineChart points={pts("announcements")} color="var(--ink)" label="Routes opened per minute" unit="opened" /></div>
                  <div><h3>Routes closed per minute{week ? ", hourly average" : ""}</h3><LineChart points={pts("withdrawals")} color="var(--red)" label="Routes closed per minute" unit="closed" /></div>
                </div>
              );
            }}
          </Async>
        </div>
      </div>
      <div className="band">
        <div className="wrap split">
          <div>
            <h2>Who is reporting the most change</h2>
            <p className="note" style={{ margin: "6px 0 12px" }}>Networks that feed the public collectors, ranked by how many route changes they passed on in the {range}.</p>
            <Async state={peers} what="reporting networks">
              {(d) => (
                <div className="scroll"><table>
                  <thead><tr><th>Network</th><th className="r">Changes</th><th className="r">Closed</th><th style={{ width: "26%" }} /></tr></thead>
                  <tbody>{d.items.map((p) => (
                    <tr key={p.peer_asn}><td><Net asn={p.peer_asn} name={p.name} country={p.country} /></td><td className="r">{fmt(p.updates)}</td><td className="r">{pct(p.withdraw_rate)}</td>
                      <td><Meter value={p.updates} max={d.items[0]?.updates ?? 1} /></td></tr>
                  ))}</tbody>
                </table></div>
              )}
            </Async>
          </div>
          <div>
            <h2>Whose routes keep changing</h2>
            <p className="note" style={{ margin: "6px 0 12px" }}>Networks whose own addresses were re-opened most often in the {range}. A long bar can mean maintenance, instability, or simply a very large network.</p>
            <Async state={origins} what="changing networks">
              {(d) => (
                <div className="scroll"><table>
                  <thead><tr><th>Network</th><th className="r">Changes</th><th style={{ width: "30%" }} /></tr></thead>
                  <tbody>{d.items.map((o) => (
                    <tr key={o.origin_asn}><td><Net asn={o.origin_asn} name={o.name} country={o.country} /></td><td className="r">{fmt(o.announcements)}</td>
                      <td><Meter value={o.announcements} max={d.items[0]?.announcements ?? 1} /></td></tr>
                  ))}</tbody>
                </table></div>
              )}
            </Async>
          </div>
        </div>
      </div>
    </>
  );
}
