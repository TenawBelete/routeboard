import { useEffect } from "react";
import { Health, usePoll } from "./api";
import { usePath } from "./nav";
import { useLive } from "./live";
import { useOffline } from "./offline";
import { navigate } from "./nav";
import { Contact } from "./components/Contact";
import Home from "./pages/Home";
import Live from "./pages/Live";
import Graph from "./pages/Graph";
import Model from "./pages/Model";
import About from "./pages/About";
import Lookup from "./pages/Lookup";
import Events from "./pages/Events";
import EventPage from "./pages/EventPage";
import Status from "./pages/Status";
import Countries from "./pages/Countries";

const NAV = [
  { path: "/", label: "Live data" },
  { path: "/events", label: "Events" },
  { path: "/country", label: "Countries" },
  { path: "/network", label: "Networks" },
  { path: "/graph", label: "Map" },
  { path: "/traffic", label: "Traffic" },
  { path: "/model", label: "Forecast" },
  { path: "/about", label: "How it works" },
];

function route(path: string): { el: JSX.Element; title: string; section: string } {
  let m = path.match(/^\/network(?:\/(\d{1,10}))?\/?$/);
  if (m) return { el: <Lookup asn={m[1] ? Number(m[1]) : null} />, title: "Look up a network", section: "/network" };
  m = path.match(/^\/country(?:\/([A-Za-z]{2}))?\/?$/);
  if (m) return { el: <Countries cc={m[1] ? m[1].toUpperCase() : null} />, title: "Countries", section: "/country" };
  m = path.match(/^\/event\/(\d{1,12})\/?$/);
  if (m) return { el: <EventPage id={Number(m[1])} />, title: "Event", section: "/events" };
  switch (path.replace(/\/$/, "") || "/") {
    case "/": return { el: <Home />, title: "", section: "/" };
    case "/events": return { el: <Events />, title: "Events", section: "/events" };
    case "/graph": return { el: <Graph />, title: "Map", section: "/graph" };
    case "/traffic": case "/live": return { el: <Live />, title: "Traffic", section: "/traffic" };
    case "/model": return { el: <Model />, title: "Forecast", section: "/model" };
    case "/about": return { el: <About />, title: "How it works", section: "/about" };
    case "/status": return { el: <Status />, title: "System status", section: "" };
    default: return {
      el: <div className="band white"><div className="wrap"><h1>Nothing at this address</h1><p className="lead">The page may have moved. <a href="/">Go to the board</a> or <a href="/network">look up a network</a>.</p></div></div>,
      title: "Not found", section: "",
    };
  }
}

export default function App() {
  const path = usePath();
  const health = usePoll<Health>("/health", 20000);
  const live = useLive();
  const saved = useOffline();
  const r = route(path);
  useEffect(() => { document.title = r.title ? `${r.title} | Routeboard` : "Routeboard: the internet's live departures board"; }, [r.title]);

  // The light's colour says how the system is doing; the label always says where it leads.
  let tone = "warn", why = "Connecting";
  if (health.kind === "ok") { tone = health.data.status === "ok" ? "ok" : "warn"; why = health.data.status === "ok" ? "Everything is working" : "Data is delayed"; }
  else if (health.kind === "error") { tone = "bad"; why = "The site cannot reach its data"; }
  if (tone === "ok" && (live.status === "down" || !live.feedUp)) { tone = "warn"; why = "The live stream is down"; }
  // While the server is away (saved data is showing), the status light, link and page are hidden.
  const offline = saved !== null;
  useEffect(() => { if (offline && path === "/status") { history.replaceState(null, "", "/"); navigate("/"); } }, [offline, path]);

  return (
    <>
      <a className="skip" href="#main">Skip to content</a>
      <header className="top">
        <div className="wrap">
          <a className="brand" href="/"><svg width="28" height="28" viewBox="0 0 32 32" aria-hidden="true"><rect width="32" height="32" rx="2" fill="#101820" /><path d="M7 22L16 9l9 13" fill="none" stroke="#ffd200" strokeWidth="4" /></svg>Routeboard</a>
          <nav aria-label="Pages">
            {NAV.map((n) => <a key={n.path} href={n.path} className={n.path === r.section ? "active" : ""} aria-current={n.path === r.section ? "page" : undefined}>{n.label}</a>)}
          </nav>
          {!offline && <a className={`status ${tone}`} href="/status" title={why} aria-label={`System status: ${why}`}><i /><span>System status</span></a>}
        </div>
      </header>
      <main id="main">{r.el}</main>
      <footer><div className="wrap">
        <span>Source: <a href="https://ris.ripe.net/" target="_blank" rel="noreferrer noopener">RIPE RIS Live</a>, a public feed of internet routing messages. We read 1 message in 50, so counts are a sample.</span>
        <span>{!offline && <a href="/status">System status</a>} <a href="https://github.com/TenawBelete/routeboard" target="_blank" rel="noreferrer noopener">Source code</a> <a href="/about">How it works</a></span>
        <span>Built by Tenaw Belete. <Contact compact /></span>
      </div></footer>
    </>
  );
}
