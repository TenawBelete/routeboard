import { useEffect, useMemo, useState } from "react";
import { Country, CountryRow, ago, countryName, flag, fmt, pct, usePoll } from "../api";
import { navigate } from "../nav";
import { RoutePath, useLive } from "../live";
import { LineChart } from "../components/LineChart";
import { Wire } from "../components/Live";
import { WorldMap } from "../components/WorldMap";
import { Async, Meter, Net, Search, Seg } from "../components/ui";
import { EventRows } from "./Events";

function headline(c: Country, name: string): string {
  const d = c.dependence;
  if (d.top_share == null) return `We saw no foreign network carrying routes into ${name} in the last ${c.window_days} days.`;
  if (!c.enough_data) {
    const seen = c.upstream_networks.slice(0, 3).map((u) => u.name ?? `AS${u.asn}`).join(", ");
    return `${name} is too quiet for a reliable picture: only ${fmt(c.routes_observed)} ${c.routes_observed === 1 ? "route" : "routes"} into it appeared in our sample over the last ${c.window_days} days. The carriers seen were ${seen}. Shares are not shown because so few observations could mislead.`;
  }
  if (d.top_share >= 0.6) return `${pct(d.top_share, 0)} of the routes into ${name} that we saw in the last ${c.window_days} days pass through a single foreign network, ${d.top_name}. If that one connection failed, most of the country would drop off the internet.`;
  if (d.upstream_networks <= 3) return `Only ${d.upstream_networks} foreign networks carry routes into ${name}. The largest, ${d.top_name}, carries ${pct(d.top_share, 0)}.`;
  return `Routes into ${name} are spread across ${fmt(d.upstream_networks)} foreign networks in ${d.upstream_countries} countries. The largest single one, ${d.top_name}, carries ${pct(d.top_share, 0)}.`;
}

/** Everything below the map on a country's page. */
function Details({ c }: { c: Country }) {
  const name = countryName(c.country);
  const live = useLive(c.country);
  const r = c.activity_ratio;
  const mood = r == null ? null : r >= 3 ? { c: "red", t: `${r.toFixed(1)} times busier than its usual` } : r >= 1.6 ? { c: "yellow", t: "Busier than its usual" } : { c: "green", t: "About its usual level" };
  if (!c.seen) return <div className="band white"><div className="wrap"><div className="notice"><b>Nothing seen today.</b> No network registered in {name} appeared in our sample of the last 24 hours.</div></div></div>;
  return (
    <>
      <div className="band white">
        <div className="wrap">
          <div className="facts">
            <div><div className="fact">{fmt(c.networks_total)}</div><p className="note">networks registered in {name} seen today</p></div>
            <div><div className="fact">{fmt(c.dependence.upstream_networks)}</div><p className="note">foreign networks carrying its routes, last {c.window_days} days</p></div>
            <div><div className="fact">{fmt(c.dependence.upstream_countries)}</div><p className="note">countries those carriers are registered in</p></div>
            <div><div className="fact">{fmt(c.changes_last_hour)}</div><p className="note">route changes for its networks in the last hour</p>{mood && <p style={{ marginTop: 6 }}><span className={`badge ${mood.c}`}>{mood.t}</span></p>}</div>
          </div>
        </div>
      </div>
      <div className="band">
        <div className="wrap split">
          <div>
            <h2>The carriers it depends on</h2>
            <p className="note" style={{ margin: "6px 0 12px" }}>Foreign networks that passed routes into {name} in the last {c.window_days} days{c.enough_data ? ", with each one's share" : ", with the number of routes seen"}.</p>
            {c.upstream_networks.length === 0 ? <p className="empty">None seen.</p> : (
              <div className="scroll"><table><tbody>{c.upstream_networks.map((u) => (
                <tr key={u.asn}><td><Net asn={u.asn} name={u.name} country={u.country} /></td><td className="r">{c.enough_data ? pct(u.share, u.share < 0.01 ? 1 : 0) : `${fmt(u.weight)} seen`}</td>
                  <td style={{ width: "34%" }}>{c.enough_data && <Meter tone={u.share >= 0.6 ? "red" : undefined} value={u.share} max={1} />}</td></tr>
              ))}</tbody></table></div>
            )}
          </div>
          <div>
            <h2>Live from {name}</h2>
            <p className="note" style={{ margin: "6px 0 12px" }}>Route changes whose path touches a network in {name}, as they arrive.</p>
            <Wire live={live} rows={8} empty={`Listening. Nothing touching ${name} has changed in the last moments; for a small country it can stay quiet for a while.`} />
          </div>
        </div>
      </div>
      <div className="band white">
        <div className="wrap split">
          <div>
            <h2>Its last 24 hours</h2>
            <p className="note" style={{ margin: "6px 0 14px" }}>Route changes for all of {name}'s networks, every five minutes. Flat is healthy; a spike or a drop to nothing means something changed.</p>
            {c.activity.length > 2
              ? <LineChart points={c.activity.map((p) => ({ t: Date.parse(p.window_start), v: p.announcements }))} color="var(--ink)" label={`Route changes for ${name}`} unit="route changes" />
              : <p className="empty">Too few changes in the last 24 hours to draw.</p>}
          </div>
          <div>
            <h2>Networks inside {name}</h2>
            <p className="note" style={{ margin: "6px 0 12px" }}>The most connected of the {fmt(c.networks_total)} seen today. {c.domestic_links > 0 ? `They have ${fmt(c.domestic_links)} direct ${c.domestic_links === 1 ? "link" : "links"} among themselves.` : ""}</p>
            <div className="scroll"><table><tbody>{c.networks.map((n) => (
              <tr key={n.asn}><td><Net asn={n.asn} name={n.name} /></td><td className="r note">{fmt(n.hub_score)} {n.hub_score === 1 ? "connection" : "connections"}</td></tr>
            ))}</tbody></table></div>
          </div>
        </div>
      </div>
      {(c.events.length > 0 || c.downstream_countries.length > 0) && (
        <div className="band">
          <div className="wrap split">
            <div>
              <h2>Recent events</h2>
              <p className="note" style={{ margin: "6px 0 12px" }}>Unusual activity by {name}'s networks in the last seven days.</p>
              {c.events.length ? <EventRows items={c.events} /> : <p className="empty">Nothing unusual recorded.</p>}
            </div>
            <div>
              <h2>Countries it carries routes for</h2>
              <p className="note" style={{ margin: "6px 0 12px" }}>Where {name}'s networks act as the carrier for others.</p>
              {c.downstream_countries.length ? (
                <table><tbody>{c.downstream_countries.slice(0, 8).map((d) => (
                  <tr key={d.country}><td><a href={`/country/${d.country}`}>{flag(d.country)} {countryName(d.country)}</a></td><td className="r">{pct(d.share, 0)}</td>
                    <td style={{ width: "34%" }}><Meter value={d.share} max={c.downstream_countries[0].share} /></td></tr>
                ))}</tbody></table>
              ) : <p className="empty">None seen.</p>}
            </div>
          </div>
        </div>
      )}
      <div className="band white">
        <div className="wrap">
          <p className="note" style={{ maxWidth: "84ch" }}>
            A carrier's country is where the company is registered. For a global carrier that is not where the cable lands: a line to the United States or Sweden usually means an American or Swedish company carries the routes, not that the data travels there. The way out of {name} usually uses the same carriers, but only the way in is visible from outside.
            {c.computed_at && <> Connections cover the last {c.window_days} days (updated {ago(c.computed_at)}) of public routing messages, sampled 1 in 50. This shows which routes exist and who carries them, not how much traffic flows or what it contains.</>}
          </p>
        </div>
      </div>
    </>
  );
}

/**
 * The Countries page and a single country's page are one component on purpose: the map stays on screen
 * when a country is clicked, so it can fly from the whole world into that country instead of being replaced.
 */
export default function Countries({ cc }: { cc: string | null }) {
  const all = usePoll<{ items: CountryRow[] }>("/api/countries", 300000);
  const one = usePoll<Country>(`/api/country/${cc ?? "US"}`, 60000);
  const c = cc && one.kind === "ok" && one.data.country === cc ? one.data : null;
  const name = cc ? countryName(cc) : "";
  const live = useLive(cc);
  const [zoomed, setZoomed] = useState(false);

  useEffect(() => { document.title = cc ? `${name} | Routeboard` : "Countries | Routeboard"; }, [cc, name]);
  // Arriving at a country: show the whole world for a moment, then fly in.
  useEffect(() => { setZoomed(false); if (!cc) return; const id = setTimeout(() => setZoomed(true), 500); return () => clearTimeout(id); }, [cc]);

  // The map shows real route changes only. When the country is quiet, its last real ones are replayed and labelled as such.
  const [mode, setMode] = useState<"live" | "replay" | "waiting">("waiting");
  const recent = live.recent;
  useEffect(() => {
    if (!cc) return;
    let lastLive = 0, i = 0;
    const onRoute = (ev: Event) => { const d = (ev as CustomEvent<RoutePath>).detail; if (d.scope === cc && !d.replay) lastLive = Date.now(); };
    window.addEventListener("routeboard:route", onRoute);
    const id = setInterval(() => {
      const quiet = Date.now() - lastLive > 6000;
      setMode(!quiet ? "live" : recent.length ? "replay" : "waiting");
      if (quiet && recent.length && !document.hidden) {
        const r = recent[recent.length - 1 - (i++ % recent.length)];
        window.dispatchEvent(new CustomEvent<RoutePath>("routeboard:route", { detail: { path: r.path, pc: r.pc, scope: cc, replay: true } }));
      }
    }, 700);
    return () => { clearInterval(id); window.removeEventListener("routeboard:route", onRoute); };
  }, [cc, recent]);
  const newest = recent.length ? new Date(recent[recent.length - 1].t * 1000).toISOString().slice(11, 16) : null;

  // Draw the partners that matter (3% or more); with too little data draw them all at equal weight.
  const partners = useMemo(() => !c ? [] : c.upstream_countries.filter((u) => !c.enough_data || u.share >= 0.03).slice(0, 8)
    .map((u) => ({ cc: u.country, share: c.enough_data ? u.share : 0.15, label: c.enough_data })), [c]);
  const shade = useMemo(() => { const s: Record<string, number> = {}; if (all.kind === "ok") all.data.items.forEach((x) => { s[x.country] = x.networks; }); return s; }, [all]);

  return (
    <>
      <div className="band white tight">
        <div className="wrap">
          {cc ? (
            <>
              <p className="note"><a href="/country">All countries</a></p>
              <h1 style={{ marginTop: 8 }}>{flag(cc)} How {name} connects to the internet</h1>
              <p className="lead">{c ? (c.seen ? headline(c, name) : `No network registered in ${name} appeared in our sample today.`) : "Reading the latest map…"}</p>
            </>
          ) : (
            <>
              <h1>Countries</h1>
              <p className="lead">Every country reaches the internet through a handful of carriers. Some have dozens of ways in; a few depend on one or two. Click a country on the map and it will fly you there.</p>
              <Search />
            </>
          )}
        </div>
      </div>

      <div className="band">
        <div className="wrap">
          <div className="rowhead">
            <h2>{cc ? "The way in" : "Route changes, as they happen"}</h2>
            {cc && <Seg value={zoomed ? "in" : "out"} options={[{ v: "in", l: "Close-up" }, { v: "out", l: "Whole world" }]} onChange={(v) => setZoomed(v === "in")} label="Map view" />}
          </div>
          <p className="note" style={{ margin: "0 0 14px", maxWidth: "84ch" }}>
            {cc
              ? <>The lines join {name} to the countries whose carriers bring routes into it{c && !c.enough_data ? "; they are drawn equal because there is too little data to weigh them" : "; a thicker line carries a larger share"}. Each moving dot is a real route change travelling country to country along its own path. Switch to the whole world to follow the far ones.</>
              : <>Darker means more networks seen today. Each moving dot is a real route change happening now, travelling country to country along its path.</>}
          </p>
          <div className="mapframe">
            <WorldMap focus={cc ?? undefined} partners={partners} zoomed={!!cc && zoomed} shade={cc ? undefined : shade} flows={cc} onPick={(x) => navigate(`/country/${x}`)} />
          </div>
          {cc ? (
            <p className="mapstate" aria-live="polite">
              {live.status !== "live" || !live.feedUp ? "The live stream is not connected, so no dots are moving."
                : mode === "live" ? <><b className="on" /> Live: these dots are route changes touching {name} right now.</>
                : mode === "replay" ? <><b /> {name} is quiet at the moment. Replaying its last {recent.length} real route {recent.length === 1 ? "change" : "changes"} (most recent at {newest} UTC).</>
                : <><b /> Listening. No route change touching {name} has arrived since the live service started.</>}
            </p>
          ) : <p className="note" style={{ marginTop: 10 }}>Borders follow United Nations usage; the map is for orientation and takes no position on disputes.</p>}
        </div>
      </div>

      {cc ? <Async state={one} what="country profile">{(d) => d.country === cc ? <Details key={d.country} c={d} /> : <div className="empty wrap">Loading {name}…</div>}</Async> : (
        <div className="band white">
          <div className="wrap">
            <Async state={all} what="countries">
              {(d) => (
                <>
                  <div className="scroll"><table>
                    <thead><tr><th>Country</th><th className="r">Networks seen</th><th className="r">Route changes, last hour</th><th style={{ width: "26%" }} /></tr></thead>
                    <tbody>{d.items.slice(0, 20).map((x) => (
                      <tr key={x.country}><td><a href={`/country/${x.country}`}>{flag(x.country)} {countryName(x.country)}</a></td><td className="r">{fmt(x.networks)}</td>
                        <td className="r">{fmt(x.changes_last_hour)}</td><td><Meter value={x.networks} max={d.items[0].networks} /></td></tr>
                    ))}</tbody>
                  </table></div>
                  <p className="note" style={{ marginTop: 12 }}>The 20 countries with the most networks. Use the search box, or click the map, for any other.</p>
                </>
              )}
            </Async>
          </div>
        </div>
      )}
    </>
  );
}
