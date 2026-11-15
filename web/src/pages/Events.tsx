import { useState } from "react";
import { EventRow, usePoll } from "../api";
import { Async, Seg } from "../components/ui";

const hhmm = (iso: string) => new Date(iso).toISOString().slice(11, 16);
const day = (iso: string) => new Date(iso).toLocaleDateString("en-GB", { weekday: "long", day: "numeric", month: "long", timeZone: "UTC" });

export function EventRows({ items }: { items: EventRow[] }) {
  return (
    <div className="board" role="table" aria-label="Events">
      <div className="row head" role="row"><span>Time</span><span>What happened</span><span style={{ justifySelf: "end" }}>Status</span></div>
      {items.map((e) => (
        <a className="row" role="row" key={e.id} href={`/event/${e.id}`}>
          <span className="t">{hhmm(e.started_at)}</span>
          <span><b>{e.title}</b><span className="d">{e.detail}</span></span>
          <span className={`tag ${e.severity}`}>{e.severity === "alert" ? "Alert" : "Watch"}</span>
        </a>
      ))}
    </div>
  );
}

export default function Events() {
  const [days, setDays] = useState(7);
  const [kind, setKind] = useState<"all" | "burst" | "surge">("all");
  const st = usePoll<{ items: EventRow[] }>(`/api/events?days=${days}&limit=300${kind === "all" ? "" : `&kind=${kind}`}`, 60000);

  return (
    <>
      <div className="band white">
        <div className="wrap">
          <h1>Events</h1>
          <p className="lead">Every time the routing system does something out of the ordinary, it is recorded here: a sudden burst of closed routes, or one network changing far more than its usual. Each event has its own page you can share.</p>
          <p className="note" style={{ marginTop: 14 }}>Follow along in a feed reader: <a href="/api/events.atom">events feed</a>.</p>
        </div>
      </div>
      <div className="band">
        <div className="wrap">
          <div className="rowhead">
            <Seg value={kind} options={[{ v: "all", l: "All events" }, { v: "burst", l: "Bursts of closures" }, { v: "surge", l: "Busy networks" }]} onChange={setKind} label="Kind of event" />
            <Seg value={days} options={[{ v: 1, l: "Today" }, { v: 7, l: "7 days" }, { v: 30, l: "30 days" }]} onChange={setDays} label="Period" />
          </div>
          <Async state={st} what="events">
            {(d) => {
              if (d.items.length === 0) return <div className="notice"><b>Nothing out of the ordinary in this period.</b> Events appear here within about five minutes of happening.</div>;
              const groups: [string, EventRow[]][] = [];
              d.items.forEach((e) => { const k = day(e.started_at); const g = groups[groups.length - 1]; if (g && g[0] === k) g[1].push(e); else groups.push([k, [e]]); });
              return <div className="stack">{groups.map(([k, items]) => <div key={k}><h3 style={{ margin: "18px 0 10px" }}>{k}</h3><EventRows items={items} /></div>)}</div>;
            }}
          </Async>
          <p className="note" style={{ marginTop: 18 }}>Times are UTC. An event is judged against the previous 24 hours, so a busy day raises the bar for what counts as unusual.</p>
        </div>
      </div>
    </>
  );
}
