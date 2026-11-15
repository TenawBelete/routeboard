import { useCallback, useState } from "react";
import { GraphEdge, GraphNode, GraphRun, ago, fmt, pct, usePoll } from "../api";
import { NetworkMap } from "../components/NetworkMap";
import { useLive } from "../live";
import { Async, Meter, Net, Seg } from "../components/ui";

export default function Graph() {
  const [by, setBy] = useState<"pagerank" | "hub">("pagerank");
  const [sel, setSel] = useState<number | null>(null);
  const run = usePoll<GraphRun>("/api/graph/summary", 60000);
  const nodes = usePoll<{ items: GraphNode[] }>(`/api/graph/nodes?order_by=${by}&limit=15`, 60000);
  const edges = usePoll<{ items: GraphEdge[] }>("/api/graph/edges?core=120&limit=320", 300000);
  const busiest = usePoll<{ items: GraphEdge[] }>("/api/graph/edges?limit=10", 300000);
  useLive();   // keeps the live stream open so the map can show real route changes
  const onSelect = useCallback((asn: number | null) => setSel(asn), []);

  return (
    <>
      <div className="band white">
        <div className="wrap">
          <h1>Who the internet runs through</h1>
          <p className="lead">No one owns the internet. It is thousands of networks that agree to carry each other's traffic. A few of them carry far more than the rest; if one of those stumbles, everyone notices.</p>
          <Async state={run} what="map figures">
            {(r) => (
              <div className="facts" style={{ marginTop: 30 }}>
                <div><div className="fact">{fmt(r.n_nodes)}</div><p className="note">networks seen in the last {r.window_hours} hours</p></div>
                <div><div className="fact">{fmt(r.n_edges)}</div><p className="note">direct connections between them</p></div>
                <div><div className="fact">{pct(r.largest_component_share, 0)}</div><p className="note">can reach each other, as they should</p></div>
                <div><div className="fact">{ago(r.computed_at)}</div><p className="note">last recalculated; it runs every hour</p></div>
              </div>
            )}
          </Async>
        </div>
      </div>
      <div className="band">
        <div className="wrap">
          <div className="rowhead">
            <h2>The core of the internet</h2>
          </div>
          <Async state={edges} what="map">
            {(d) => (
              <NetworkMap edges={d.items} selected={sel} onSelect={onSelect} />
            )}
          </Async>
          {edges.kind === "ok" && <p className="note" style={{ marginTop: 10, maxWidth: "90ch" }}>The 120 most relied-on networks and the {edges.data.items.length} busiest connections between them. Bigger dot, more routes. A moving yellow dot is a real route change happening now. Point at a network to trace its links. Click one to focus on it: the map flies to it and shows only the changes passing through it.</p>}
        </div>
      </div>
      <div className="band white">
        <div className="wrap split">
          <div>
            <div className="rowhead">
              <h2>Most relied-on networks</h2>
              <Seg value={by} options={[{ v: "pagerank", l: "By influence" }, { v: "hub", l: "By connections" }]} onChange={setBy} label="Ranking" />
            </div>
            <p className="note" style={{ marginBottom: 12 }}>{by === "pagerank"
              ? "Influence is PageRank, the method Google used to rank web pages: a network matters if important networks route through it."
              : "Connections counts how many other networks each one links to directly."} Click a row to find it on the map.</p>
            <Async state={nodes} what="rankings">
              {(d) => (
                <div className="scroll"><table>
                  <thead><tr><th>Rank</th><th>Network</th><th className="r">Connections</th><th style={{ width: "24%" }}>{by === "pagerank" ? "Influence" : "Connections"}</th></tr></thead>
                  <tbody>{d.items.map((n) => (
                    <tr key={n.asn} className={`pick ${sel === n.asn ? "sel" : ""}`} onClick={() => setSel(sel === n.asn ? null : n.asn)}>
                      <td>{by === "pagerank" ? n.pagerank_rank : n.hub_rank}</td><td><Net asn={n.asn} name={n.name} country={n.country} /></td>
                      <td className="r">{fmt(n.hub_score)}</td>
                      <td><Meter value={by === "pagerank" ? n.pagerank : n.hub_score} max={by === "pagerank" ? d.items[0]?.pagerank ?? 1 : d.items[0]?.hub_score ?? 1} /></td></tr>
                  ))}</tbody>
                </table></div>
              )}
            </Async>
          </div>
          <div>
            <h2>Busiest single connections</h2>
            <p className="note" style={{ margin: "6px 0 12px" }}>Pairs of networks that passed the most routes between them today.</p>
            <Async state={busiest} what="connections">
              {(d) => (
                <div className="scroll"><table>
                  <thead><tr><th>Between</th><th>And</th><th className="r">Routes</th></tr></thead>
                  <tbody>{d.items.map((e) => (
                    <tr key={`${e.src}-${e.dst}`}><td><Net asn={e.src} name={e.src_name} /></td><td><Net asn={e.dst} name={e.dst_name} /></td><td className="r">{fmt(e.weight)}</td></tr>
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
