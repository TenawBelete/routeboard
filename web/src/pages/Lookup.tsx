import { navigate } from "../nav";
import { useMemo } from "react";
import { Neighbour, Network, ago, countryName, flag, fmt, ordinal, usePoll } from "../api";
import { LineChart } from "../components/LineChart";
import { NetworkCanvas } from "../components/NetworkCanvas";
import { Async, Meter, Net, Search } from "../components/ui";

function Neighbours({ title, help, rows }: { title: string; help: string; rows: Neighbour[] }) {
  return (
    <div>
      <h3>{title}</h3><p className="note" style={{ margin: "4px 0 10px" }}>{help}</p>
      {rows.length === 0 ? <p className="empty">None seen today.</p> : (
        <table><tbody>{rows.map((n) => (
          <tr key={n.asn}><td><Net asn={n.asn} name={n.name} country={n.country} /></td><td className="r">{fmt(n.weight)}</td>
            <td style={{ width: "30%" }}><Meter value={n.weight} max={rows[0].weight} /></td></tr>
        ))}</tbody></table>
      )}
    </div>
  );
}

function Profile({ n }: { n: Network }) {
  const title = n.name ?? `Unnamed network AS${n.asn}`;
  const star = useMemo(() => [
    ...n.upstream.map((u) => ({ src: u.asn, dst: n.asn, weight: u.weight })),
    ...n.downstream.map((d) => ({ src: n.asn, dst: d.asn, weight: d.weight })),
  ], [n]);
  const names = useMemo(() => {
    const m: Record<number, string> = { [n.asn]: title };
    [...n.upstream, ...n.downstream].forEach((x) => { if (x.name) m[x.asn] = x.name; });
    return m;
  }, [n, title]);
  const r = n.activity_ratio;
  const mood = r == null ? null : r >= 3 ? { c: "red", t: `${r.toFixed(1)} times busier than its usual` } : r >= 1.6 ? { c: "yellow", t: "Busier than its usual" } : { c: "green", t: "About its usual level" };

  return (
    <>
      <div className="band white">
        <div className="wrap">
          <p className="note"><a href="/network">Look up another network</a></p>
          <h1 style={{ marginTop: 10 }}>{title}</h1>
          <p className="lead">{flag(n.country)} {countryName(n.country) || "Country not registered"}, network number AS{n.asn}{n.handle ? `, registered as ${n.handle}` : ""}.</p>
          {!n.seen && <div className="notice" style={{ marginTop: 22 }}><b>Not seen today.</b> This network did not appear in our sample of the last 24 hours. It may be small, quiet, or not connected at the moment.</div>}
          {n.seen && (
            <div className="facts" style={{ marginTop: 32 }}>
              {n.graph && <div><div className="fact">{ordinal(n.graph.pagerank_rank)}</div><p className="note">most relied-on for carrying other networks' routes, out of {fmt(n.graph.n_nodes)}</p></div>}
              {n.graph && <div><div className="fact">{fmt(n.graph.hub_score)}</div><p className="note">networks it connects to directly</p></div>}
              <div><div className="fact">{fmt(n.announcements_last_hour)}</div><p className="note">route changes for its addresses in the last hour</p>{mood && <p style={{ marginTop: 6 }}><span className={`badge ${mood.c}`}>{mood.t}</span></p>}</div>
              {n.risk && <div><div className="fact">{Math.round(n.risk.probability * 100)}<span className="note"> / 100</span></div><p className="note">forecast risk of dropping routes in the next five minutes</p></div>}
            </div>
          )}
        </div>
      </div>
      {n.seen && (
        <div className="band">
          <div className="wrap split">
            <div>
              <h2>Its last 24 hours</h2>
              <p className="note" style={{ margin: "6px 0 14px" }}>How often routes to {title}'s addresses were re-opened, every five minutes. Flat is healthy; spikes mean something changed.</p>
              {n.activity.length > 2
                ? <LineChart points={n.activity.map((p) => ({ t: Date.parse(p.window_start), v: p.announcements }))} color="var(--ink)" label={`Route changes for ${title}`} unit="route changes" />
                : <p className="empty">No changes to its own routes in the last 24 hours, which is what a stable network looks like.</p>}
              {n.peer && <p className="note" style={{ marginTop: 14 }}>{title} also reports directly to the public collectors we listen to: it relayed {fmt(n.peer.updates)} route changes today, {fmt(n.peer.withdrawals)} of them closures.</p>}
            </div>
            <div>
              <h2>Its neighbourhood</h2>
              <p className="note" style={{ margin: "6px 0 14px" }}>The networks {title} exchanged the most routes with today. Click one to open it.</p>
              {star.length ? <div className="mapbox small"><NetworkCanvas edges={star} names={names} interactive labels={12} pulses={18} selected={n.asn} onSelect={(a) => { if (a && a !== n.asn) navigate(`/network/${a}`); }} /></div>
                : <p className="empty">No direct connections seen today.</p>}
            </div>
          </div>
        </div>
      )}
      {n.seen && (n.upstream.length > 0 || n.downstream.length > 0) && (
        <div className="band white">
          <div className="wrap split even">
            <Neighbours title="Reaches the world through" help="Networks that passed this network's routes onward. The number is how many routes we saw." rows={n.upstream} />
            <Neighbours title="Carries routes for" help="Networks whose routes travelled through this one." rows={n.downstream} />
          </div>
          {n.graph && <div className="wrap"><p className="note" style={{ marginTop: 22 }}>Connections recalculated {ago(n.graph.computed_at)} from the last {n.graph.window_hours} hours, as seen from RIPE's public collectors. Private arrangements between networks are invisible to anyone outside them.</p></div>}
        </div>
      )}
    </>
  );
}

export default function Lookup({ asn }: { asn: number | null }) {
  const state = usePoll<Network>(asn ? `/api/network/${asn}` : "/api/network/15169", 60000);
  if (!asn)
    return (
      <div className="band white">
        <div className="wrap">
          <h1>Look up a network</h1>
          <p className="lead">Every company that runs part of the internet appears here: phone and broadband providers, cloud platforms, universities, banks. Search by name to see how central it is, who it connects to, and whether today looks normal for it.</p>
          <Search autoFocus />
        </div>
      </div>
    );
  return <Async state={state} what="network profile">{(n) => <Profile key={n.asn} n={n} />}</Async>;
}
