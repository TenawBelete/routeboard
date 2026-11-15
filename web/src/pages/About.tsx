import { Contact } from "../components/Contact";

const BOX = (x: number, y: number, w: number, title: string, sub: string, hi = false) => (
  <g key={title}>
    <rect x={x} y={y} width={w} height="64" rx="2" fill={hi ? "#ffd200" : "#fff"} stroke="#101820" strokeWidth="2" />
    <text x={x + w / 2} y={y + 28} textAnchor="middle" fill="#101820" fontSize="16" fontWeight="800">{title}</text>
    <text x={x + w / 2} y={y + 48} textAnchor="middle" fill="#3d4850" fontSize="13">{sub}</text>
  </g>
);
const ARROW = (x1: number, y1: number, x2: number, y2: number, k: string) => (
  <line key={k} x1={x1} y1={y1} x2={x2} y2={y2} stroke="#101820" strokeWidth="2" markerEnd="url(#ah)" />
);

const CHOICES: [string, string][] = [
  ["Nothing is counted twice", "If a step crashes and repeats its work, the result replaces the old one instead of adding to it. Every batch carries an ID, so a replay is recognised and skipped."],
  ["History survives the clean-up", "Raw messages are kept 3 days and cleaned events 14 days. Before anything is deleted, each day is condensed into a small permanent table of connections."],
  ["One fixed bill", "Everything runs on a single rented server. Nothing is billed by usage, so the monthly cost cannot grow by surprise."],
  ["A forecast that admits its limits", "The model is tested only on data from after its training period and shown next to a coin flip. With too little history it says so instead of printing a score."],
  ["Closed by default", "Only this website is reachable from the internet. The database, queue and storage listen inside the server, and the service behind these pages can read data but never change it."],
  ["What it does not do", "It reads 1 message in 50, so totals are a fraction of the real volume; proportions and trends are the things to read. One server means no backup machine if it fails."],
];

export default function About() {
  return (
    <>
      <div className="band white">
        <div className="wrap">
          <h1>How it works</h1>
          <p className="lead">Routers around the world publish every route change to a public feed run by RIPE, the body that coordinates internet addresses in Europe. This site reads that feed and turns it into the pages you have seen, in under a minute.</p>
        </div>
      </div>
      <div className="band">
        <div className="wrap">
          <h2>The journey of one message</h2>
          <div className="scroll" style={{ marginTop: 20 }}>
            <svg className="arch" viewBox="0 0 1080 300" role="img" aria-label="RIPE's live feed goes to a collector program, then a queue, then a stream processor, which writes to long-term storage and to a database. Analysis jobs read both. A read-only service reads the database and this website reads that service." style={{ minWidth: 760 }}>
              <defs><marker id="ah" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto"><path d="M0 0L10 5L0 10z" fill="#101820" /></marker></defs>
              {BOX(4, 20, 156, "RIPE live feed", "public route messages", true)}
              {BOX(200, 20, 150, "Collector", "Python, keeps 1 in 50")}
              {BOX(390, 20, 150, "Queue", "Redpanda, holds 6 hours")}
              {BOX(580, 20, 170, "Stream processor", "Spark, every 30 seconds")}
              {BOX(800, 20, 276, "Long-term storage", "Delta Lake: raw 3 days, clean 14 days")}
              {BOX(580, 210, 170, "Database", "Postgres, ready answers")}
              {BOX(800, 210, 150, "Analysis", "map + forecast")}
              {BOX(390, 210, 150, "Read-only service", "FastAPI")}
              {BOX(200, 210, 150, "This website", "React, served by Caddy", true)}
              {ARROW(160, 52, 198, 52, "a")}{ARROW(350, 52, 388, 52, "b")}{ARROW(540, 52, 578, 52, "c")}{ARROW(750, 52, 798, 52, "d")}
              {ARROW(665, 84, 665, 208, "e")}{ARROW(875, 84, 875, 208, "f")}{ARROW(800, 242, 752, 242, "g")}
              {ARROW(580, 242, 542, 242, "h")}{ARROW(390, 242, 352, 242, "i")}
              <text x="675" y="150" fill="#3d4850" fontSize="13">per-minute totals</text>
              <text x="885" y="150" fill="#3d4850" fontSize="13">route history</text>
            </svg>
          </div>
        </div>
      </div>
      <div className="band white">
        <div className="wrap">
          <h2>Decisions worth explaining</h2>
          <div className="explain">
            {CHOICES.map(([t, b]) => <div key={t}><h3>{t}</h3><p>{b}</p></div>)}
          </div>
        </div>
      </div>
      <div className="band">
        <div className="wrap">
          <h2>Contact me</h2>
          <p className="lead">I'm Tenaw Belete. I designed and built this platform. If you have a question about it, or about working together, reach me here.</p>
          <Contact />
        </div>
      </div>
    </>
  );
}
