import { ModelRun, Prediction, ago, fmt, usePoll } from "../api";
import { Async, Meter, Net } from "../components/ui";

const FEATURE_WORDS: Record<string, string> = {
  log_updates_t0: "How busy the network is right now", delta_updates: "Whether its activity just jumped",
  rate_t0: "Share of routes it closed in the last 5 minutes", rate_t1: "Share closed 5 to 10 minutes ago",
  rate_t2: "Share closed 10 to 15 minutes ago", rate_t3: "Share closed 15 to 20 minutes ago",
  hour_sin: "Time of day (morning or evening)", hour_cos: "Time of day (day or night)",
};
const outOf = (p: number | null) => (p == null || p <= 0 ? null : Math.max(1, Math.round(1 / p)));

export default function Model() {
  const run = usePoll<ModelRun>("/api/model/summary", 60000);
  const preds = usePoll<{ items: Prediction[] }>("/api/model/predictions?limit=12", 60000);

  return (
    <>
      <div className="band white">
        <div className="wrap">
          <h1>Forecast: who may wobble next</h1>
          <p className="lead">Like a weather forecast for networks. A small statistical model watches how each network behaved over the last 20 minutes and scores how likely it is to close an unusual share of its routes in the next five.</p>
        </div>
      </div>
      <Async state={run} what="forecast">
        {(m) => {
          const auc = m.auc ?? 0.5, coefs = Object.entries(m.coefficients ?? {}).sort((a, b) => Math.abs(b[1]) - Math.abs(a[1]));
          const maxC = Math.max(0.001, ...coefs.map(([, v]) => Math.abs(v)));
          const right = outOf(m.precision_), caught = m.recall == null ? null : Math.round(m.recall * 10);
          return (
            <>
              <div className="band">
                <div className="wrap split wide-right">
                  <div>
                    <h2>How much to trust it</h2>
                    <div className="stack" style={{ marginTop: 16 }}>
                      {right && <p><b>About 1 warning in {right} is right.</b> Most flagged networks stay fine, so read the score as "worth a look", not "will fail".</p>}
                      {caught != null && <p><b>It catches about {caught} in 10 real events.</b> The rest arrive without warning.</p>}
                      <p><b>It beats guessing, clearly but not hugely.</b> On a scale where 0.50 is a coin flip and 1.00 is perfect, it scores {auc.toFixed(2)}.</p>
                    </div>
                    <svg className="chart" viewBox="0 0 400 66" role="img" aria-label={`Model score ${auc.toFixed(2)}; coin flip 0.50; perfect 1.00`} style={{ marginTop: 18, maxWidth: 440 }}>
                      <rect x="0" y="20" width="400" height="12" fill="#dfe4e8" />
                      <rect x="200" y="20" width={Math.max(0, (auc - 0.5) * 400)} height="12" fill="var(--ink)" />
                      <line x1="200" x2="200" y1="12" y2="40" stroke="var(--ink)" strokeWidth="2" />
                      <text x="200" y="60" textAnchor="middle">coin flip</text><text x="400" y="60" textAnchor="end">perfect</text>
                      <circle cx={auc * 400} cy="26" r="8" fill="var(--yellow)" stroke="var(--ink)" strokeWidth="2.5" />
                    </svg>
                    <p className="note" style={{ marginTop: 14 }}>Checked against {fmt(m.n_test)} later observations the model had never seen. Retrained {ago(m.trained_at)} on {fmt(m.n_train)} observations; it retrains every six hours.</p>
                  </div>
                  <div>
                    <h2>Networks to watch right now</h2>
                    <p className="note" style={{ margin: "6px 0 12px" }}>Risk score from 0 to 100. It ranks networks against each other; it is not a percentage chance.</p>
                    <Async state={preds} what="scores">
                      {(d) => (
                        <div className="scroll"><table>
                          <thead><tr><th>Network</th><th className="r">Score</th><th style={{ width: "30%" }} /><th>Afterwards</th></tr></thead>
                          <tbody>{d.items.map((p) => (
                            <tr key={`${p.window_start}-${p.peer_asn}`}><td><Net asn={p.peer_asn} name={p.name} country={p.country} /></td><td className="r">{Math.round(p.probability * 100)}</td>
                              <td><Meter tone={p.probability >= 0.9 ? "red" : undefined} value={p.probability} max={1} /></td>
                              <td>{p.actual == null ? <span className="note">Not checked yet</span> : p.actual ? <span className="badge red">Closed routes</span> : <span className="note">Stayed normal</span>}</td></tr>
                          ))}</tbody>
                        </table></div>
                      )}
                    </Async>
                  </div>
                </div>
              </div>
              <div className="band white">
                <div className="wrap">
                  <h2>What the forecast looks at</h2>
                  <p className="note" style={{ margin: "6px 0 14px" }}>A bar to the right raises the risk score; a bar to the left lowers it. Longer means it matters more.</p>
                  <div className="scroll"><table style={{ maxWidth: 860 }}>
                    <tbody>{coefs.map(([k, v]) => (
                      <tr key={k}><td style={{ width: "46%" }}>{FEATURE_WORDS[k] ?? k}</td>
                        <td><svg viewBox="0 0 400 14" className="chart" style={{ height: 14 }} preserveAspectRatio="none" aria-hidden="true">
                          <rect x={v >= 0 ? 200 : 200 - (Math.abs(v) / maxC) * 196} y="1" width={(Math.abs(v) / maxC) * 196} height="12" fill={v >= 0 ? "var(--red)" : "var(--ink)"} />
                          <line x1="200" x2="200" y1="0" y2="14" stroke="var(--ink)" />
                        </svg></td>
                        <td className="r" style={{ width: 150 }}>{v >= 0 ? "raises risk" : "lowers risk"}</td></tr>
                    ))}</tbody>
                  </table></div>
                </div>
              </div>
            </>
          );
        }}
      </Async>
    </>
  );
}
