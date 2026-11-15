import { Briefing, GraphEdge, GraphRun, fmt, usePoll } from "../api";
import { NetworkMap } from "../components/NetworkMap";
import { Pulse, Wire } from "../components/Live";
import { useLive } from "../live";
import { Async, Search } from "../components/ui";

const TAG = { alert: "Alert", watch: "Watch", info: "Note" } as const;
const hhmm = (iso: string) => new Date(iso).toISOString().slice(11, 16);

export default function Home() {
    const brief = usePoll<Briefing>("/api/briefing", 30000);
  const run = usePoll<GraphRun>("/api/graph/summary", 300000);
  const edges = usePoll<{ items: GraphEdge[] }>("/api/graph/edges?core=70&limit=180", 300000);
  const live = useLive();
  const st = brief.kind === "ok" ? brief.data.state : null;
  const count = run.kind === "ok" ? fmt(run.data.n_nodes) : "tens of thousands of";

  return (
    <>
      <div className="band white">
        <div className="wrap split">
          <div>
            <h1>The internet's live departures board</h1>
            <p className="lead">
              The internet is {count} separate networks (Google, your phone company, your university) that keep telling each other
              which routes are open. When one stops, part of the internet goes dark for someone. This site listens to those messages around the clock.
            </p>
            <Search />
          </div>
          <div className={`sign ${st?.level ?? "normal"}`} aria-live="polite">
            <div className="big">{st ? st.label : "Reading the feed"}</div>
            <p>{st ? `About ${fmt(st.recent_per_minute)} route changes a minute over the last ten minutes. The usual is ${fmt(st.usual_per_minute)}.` : "The first reading takes a couple of minutes after the system starts."}</p>
            <Pulse live={live} dark />
          </div>
        </div>
      </div>

      <div className="band">
        <div className="wrap split">
          <div>
            <div className="rowhead" style={{ marginBottom: 0 }}><h2>Happening now</h2><a href="/events">All events</a></div>
            <p className="note" style={{ margin: "6px 0 16px" }}>Written automatically from the last six hours of data. Times are UTC.</p>
            <Async state={brief} what="briefing">
              {(b) => (
                <div className="board" role="table" aria-label="Notable events">
                  <div className="row head" role="row"><span>Time</span><span>What happened</span><span style={{ justifySelf: "end" }}>Status</span></div>
                  {b.items.length === 0 && <div className="row"><span className="t">now</span><span><b>Nothing unusual</b><span className="d">No bursts or surges in the last six hours.</span></span><span className="tag">Calm</span></div>}
                  {b.items.map((it, i) => {
                    const body = <><span className="t">{it.at ? hhmm(it.at) : "now"}</span><span><b>{it.title}</b><span className="d">{it.detail}</span></span><span className={`tag ${it.tone}`}>{TAG[it.tone]}</span></>;
                    const to = it.event_id ? `/event/${it.event_id}` : it.asn ? `/network/${it.asn}` : null;
                    return to ? <a className="row" role="row" key={i} href={to}>{body}</a> : <div className="row" role="row" key={i}>{body}</div>;
                  })}
                </div>
              )}
            </Async>
          </div>
          <div>
            <h2>The wire</h2>
            <p className="note" style={{ margin: "6px 0 16px" }}>Real route changes as they arrive, a few each second out of everything we receive.</p>
            <Wire live={live} rows={9} />
          </div>
        </div>
      </div>

      <div className="band white">
        <div className="wrap">
          <div className="rowhead"><h2>Who the internet runs through</h2><a href="/graph">Open the full map</a></div>
          <p className="note" style={{ marginBottom: 16, maxWidth: "70ch" }}>Every dot is a network, every line a direct connection that carried routes today. The biggest dots are the carriers most of the world depends on. A yellow dot moving along a line is a real route change crossing that connection right now. Click a network to focus on it: the map flies to it and shows only the changes passing through it.</p>
          <Async state={edges} what="map">
            {(d) => <NetworkMap edges={d.items} labels={9} small />}
          </Async>
        </div>
      </div>

      <div className="band">
        <div className="wrap split even">
          <div>
            <h2>Questions this site answers</h2>
            <ul className="qa">
              <li><a href="/events"><span><b>What just broke?</b><span>A running record of every unusual event, each with its own page.</span></span><i>See events</i></a></li>
              <li><a href="/country"><span><b>How does a country reach the internet?</b><span>See any country's connections on a map, and how few carriers it depends on.</span></span><i>Pick a country</i></a></li>
              <li><a href="/network"><span><b>Is my provider having a bad day?</b><span>Look up any company or provider and compare today with its normal.</span></span><i>Look it up</i></a></li>
              <li><a href="/graph"><span><b>Who does the internet depend on?</b><span>A ranked map of the networks everyone else connects through.</span></span><i>See the map</i></a></li>
              <li><a href="/model"><span><b>Who is likely to wobble next?</b><span>A forecast of which networks may drop routes in the next five minutes.</span></span><i>See the forecast</i></a></li>
              <li><a href="/traffic"><span><b>How busy is it right now?</b><span>Routes opening and closing, minute by minute.</span></span><i>See traffic</i></a></li>
            </ul>
          </div>
          <div>
            <h2>Three words you need</h2>
            <div className="stack" style={{ marginTop: 20 }}>
              <p><b>Network.</b> One organisation's piece of the internet: a phone company, a cloud provider, a university. Each has a number such as AS15169 (Google).</p>
              <p><b>Route opened.</b> A network tells its neighbours "you can reach these addresses through me". Engineers call it an announcement.</p>
              <p><b>Route closed.</b> The network takes that offer back, called a withdrawal. A few are routine. A sudden burst usually means an outage, a cut cable or a mistake.</p>
            </div>
          </div>
        </div>
      </div>
    </>
  );
}
