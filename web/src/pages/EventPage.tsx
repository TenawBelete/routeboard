import { useEffect, useState } from "react";
import { EventDetail, fmt, usePoll } from "../api";
import { LineChart } from "../components/LineChart";
import { Async, Meter, Net } from "../components/ui";

const when = (iso: string) => new Date(iso).toLocaleString("en-GB", { day: "numeric", month: "long", year: "numeric", hour: "2-digit", minute: "2-digit", timeZone: "UTC" }) + " UTC";
const local = (iso: string) => new Date(iso).toLocaleString(undefined, { hour: "2-digit", minute: "2-digit", day: "numeric", month: "short" });

function CopyLink() {
  const [done, setDone] = useState(false);
  return <button className="btn" onClick={async () => { try { await navigator.clipboard.writeText(location.href); setDone(true); setTimeout(() => setDone(false), 2500); } catch { /* clipboard blocked: the address bar still works */ } }}>{done ? "Link copied" : "Copy link"}</button>;
}

function Body({ e }: { e: EventDetail }) {
  useEffect(() => { document.title = `${e.title} | Routeboard`; }, [e.title]);
  const burst = e.kind === "burst";
  const t0 = Date.parse(e.started_at), t1 = Date.parse(e.ended_at);
  return (
    <>
      <div className="band white">
        <div className="wrap">
          <p className="note"><a href="/events">All events</a></p>
          <p style={{ marginTop: 14 }}><span className={`badge ${e.severity === "alert" ? "red" : "yellow"}`}>{e.severity === "alert" ? "Alert" : "Watch"}</span></p>
          <h1 style={{ marginTop: 10 }}>{e.title}</h1>
          <p className="lead">{e.detail}</p>
          <p className="note" style={{ marginTop: 12 }}>{when(e.started_at)} ({local(e.started_at)} your time)</p>
          <div className="actions"><CopyLink />{e.asn && <a className="btn" href={`/network/${e.asn}`}>Open {e.name ?? "this network"}</a>}</div>
        </div>
      </div>
      <div className="band">
        <div className="wrap split">
          <div>
            <h2>{burst ? "The minutes around it" : "Its activity around that hour"}</h2>
            <p className="note" style={{ margin: "6px 0 14px" }}>{burst ? "Routes closed per minute. The shaded part is the event." : "Route changes every five minutes. The shaded part is the hour that stood out."}</p>
            {e.series.length > 2
              ? <LineChart points={e.series.map((p) => ({ t: Date.parse(p.window_start), v: p.value }))} color="var(--ink)" label={e.title} unit={burst ? "closed" : "route changes"} band={[t0, t1]} />
              : <p className="empty">The minute-by-minute record for this period is no longer kept.</p>}
          </div>
          <div>
            <h2>What it means</h2>
            <div className="stack" style={{ marginTop: 14 }}>
              {burst ? <>
                <p>Many routes were taken away within the same minute. That usually has one cause: an outage, a cut cable, a misconfiguration, or a large network restarting part of its equipment.</p>
                <p>If the routes returned quickly, most people noticed nothing. If they stayed away, some part of the internet was unreachable for a while.</p>
              </> : <>
                <p>This network's routes were changed far more often than is normal for it. Frequent changes can come from maintenance, an unstable connection that keeps dropping, or a deliberate rerouting of traffic.</p>
                <p>On its own this does not mean an outage. It means the network was worth watching during that hour.</p>
              </>}
              <p className="note">Routeboard reads a sample of public routing messages. It can show that something happened and how large it was; it cannot see the cause.</p>
            </div>
          </div>
        </div>
      </div>
      {burst && e.reporters.length > 0 && (
        <div className="band white">
          <div className="wrap" style={{ maxWidth: 760 }}>
            <h2>Who saw it</h2>
            <p className="note" style={{ margin: "6px 0 12px" }}>Networks that reported the most closed routes during the event. They are witnesses, not necessarily the source: each one passes on what it hears from its neighbours.</p>
            <table><tbody>{e.reporters.map((r) => (
              <tr key={r.asn}><td><Net asn={r.asn} name={r.name} country={r.country} /></td><td className="r">{fmt(r.withdrawals)}</td>
                <td style={{ width: "34%" }}><Meter tone="red" value={r.withdrawals} max={e.reporters[0].withdrawals} /></td></tr>
            ))}</tbody></table>
          </div>
        </div>
      )}
    </>
  );
}

export default function EventPage({ id }: { id: number }) {
  const st = usePoll<EventDetail>(`/api/events/${id}`, 120000);
  if (st.kind === "empty") return <div className="band white"><div className="wrap"><h1>No event with this number</h1><p className="lead">It may have been mistyped. <a href="/events">See all events</a>.</p></div></div>;
  return <Async state={st} what="event">{(e) => <Body e={e} />}</Async>;
}
