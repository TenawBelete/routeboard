import { StatusReport, ago, fmt, usePoll } from "../api";
import { Async } from "../components/ui";

const WORD = { ok: "Working", late: "Running late", stalled: "Stalled", waiting: "Not run yet" } as const;
const TONE = { ok: "green", late: "yellow", stalled: "red", waiting: "" } as const;
const HEAD = { ok: "Everything is working", late: "Some parts are running late", stalled: "Part of the system has stalled" } as const;

export default function Status() {
  const st = usePoll<StatusReport>("/api/status", 20000);
  const lv = usePoll<{ status: string; kafka: string; clients: number; messages: number }>("/live/health", 20000);
  return (
    <>
      <div className="band white">
        <div className="wrap">
          <h1>System status</h1>
          <p className="lead">This site is the end of a chain of programs. If one link stops, the pages after it go stale. This page shows each link and when it last did its job, so you never have to wonder whether the numbers are current.</p>
        </div>
      </div>
      <div className="band">
        <div className="wrap" style={{ maxWidth: 860 }}>
          <Async state={st} what="status">
            {(s) => (
              <>
                <h2>{HEAD[s.overall]}</h2>
                <table style={{ marginTop: 16 }}>
                  <thead><tr><th>Part</th><th>Last did its job</th><th>State</th></tr></thead>
                  <tbody>{s.stages.map((x) => (
                    <tr key={x.key}>
                      <td><b>{x.label}</b><br /><span className="note">{x.what}{x.extra ? `. ${x.extra}.` : ""}</span></td>
                      <td>{x.last ? ago(x.last) : "–"}</td>
                      <td><span className={`badge ${TONE[x.state]}`}>{WORD[x.state]}</span></td>
                    </tr>
                  ))}
                    <tr>
                      <td><b>Live stream</b><br /><span className="note">Pushes route changes to this page as they arrive{lv.kind === "ok" ? `. ${fmt(lv.data.messages)} messages relayed since it started, ${lv.data.clients} ${lv.data.clients === 1 ? "viewer" : "viewers"} connected.` : "."}</span></td>
                      <td>{lv.kind === "ok" && lv.data.kafka === "connected" ? "now" : "–"}</td>
                      <td>{lv.kind === "ok" ? (lv.data.kafka === "connected" ? <span className="badge green">Working</span> : <span className="badge yellow">Reconnecting</span>) : lv.kind === "loading" ? <span className="badge">Checking</span> : <span className="badge red">Unreachable</span>}</td>
                    </tr>
                  </tbody>
                </table>
                <p className="note" style={{ marginTop: 16 }}>This page refreshes every 20 seconds.</p>
              </>
            )}
          </Async>
        </div>
      </div>
    </>
  );
}
