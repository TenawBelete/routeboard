import { navigate } from "../nav";
import { apiUrl } from "../config";
import { fromBundle } from "../offline";
import { ReactNode, useEffect, useRef, useState } from "react";
import { CountryRow, Named, SearchHit, State, countryName, flag } from "../api";

/** Renders the right thing for every state of a request, so no page shows a blank or a fake zero. */
export function Async<T>({ state, children, what }: { state: State<T>; what: string; children: (d: T) => ReactNode }) {
  if (state.kind === "loading") return <div className="empty">Loading {what}…</div>;
  if (state.kind === "error")
    return <div className="notice bad"><b>Can't load {what}.</b> {state.message}. This page retries by itself.</div>;
  if (state.kind === "empty")
    return <div className="notice"><b>No {what} yet.</b> It appears shortly after the system starts.</div>;
  return <>{children(state.data)}</>;
}

export function Meter({ value, max, tone }: { value: number; max: number; tone?: "red" | "blue" }) {
  return <div className={`meter ${tone ?? ""}`} role="presentation"><i style={{ width: `${max > 0 ? Math.min(100, (100 * value) / max) : 0}%` }} /></div>;
}

/** A network shown the way people know it: name first, number second. Links to its profile. */
export function Net({ asn, name, country }: { asn: number } & Named) {
  return (
    <a className="net" href={`/network/${asn}`}>
      <b>{name ?? "Unnamed network"}</b>
      <small>{flag(country)} AS{asn}</small>
    </a>
  );
}

export function Seg<T extends string | number>({ value, options, onChange, label }:
  { value: T; options: { v: T; l: string }[]; onChange: (v: T) => void; label: string }) {
  return (
    <div className="seg" role="group" aria-label={label}>
      {options.map((o) => <button key={String(o.v)} className={o.v === value ? "on" : ""} aria-pressed={o.v === value} onClick={() => onChange(o.v)}>{o.l}</button>)}
    </div>
  );
}

const TRY: [string, string][] = [["Google", "/network/15169"], ["Cloudflare", "/network/13335"], ["Eritrea", "/country/ER"], ["Ethiopia", "/country/ET"]];

// Countries are matched in the browser: any country whose name appears in what was typed,
// so "show me the traffic of Eritrea" finds Eritrea. This is word matching, not a language model.
let countryList: Promise<{ cc: string; name: string; key: string }[]> | null = null;
const loadCountries = () => (countryList ??= fetch(apiUrl("/api/countries")).then((r) => (r.ok ? r.json() : fromBundle<{ items: CountryRow[] }>("/api/countries").then((h) => h?.data ?? { items: [] })))
  .then((j) => (j.items as CountryRow[]).map((c) => ({ cc: c.country, name: countryName(c.country), key: countryName(c.country).toLowerCase() })))
  .catch(() => { countryList = null; return []; }));
export function matchCountries(q: string, all: { cc: string; name: string; key: string }[]) {
  const t = q.trim().toLowerCase();
  if (t.length < 2) return [];
  return all.filter((c) => (c.key.length >= 4 && t.includes(c.key)) || c.key.startsWith(t) || (t.length >= 4 && c.key.includes(t)) || c.cc.toLowerCase() === t)
    .sort((a, b) => Number(b.key.startsWith(t) || t.includes(b.key)) - Number(a.key.startsWith(t) || t.includes(a.key))).slice(0, 3);
}
type Hit = { href: string; title: string; sub: string; tag: string };

/** Type a company, provider or network number; pick a result to open its profile. */
export function Search({ autoFocus = false }: { autoFocus?: boolean }) {
  const [q, setQ] = useState("");
  const [hits, setHits] = useState<Hit[] | null>(null);
  const [cur, setCur] = useState(0);
  const seq = useRef(0);
  useEffect(() => {
    const term = q.trim();
    if (term.length < 2) { setHits(null); return; }
    const mine = ++seq.current;
    const id = setTimeout(async () => {
      try {
        const [r, all] = await Promise.all([fetch(apiUrl(`/api/search?q=${encodeURIComponent(term.slice(0, 60))}`)).catch(() => new Response("{}", { status: 503 })), loadCountries()]);
        const j = r.ok ? await r.json() : { items: [] };
        const cs: Hit[] = matchCountries(term, all).map((c) => ({ href: `/country/${c.cc}`, title: `${flag(c.cc)} ${c.name}`, sub: "How this country connects", tag: "Country" }));
        const ns: Hit[] = (j.items as SearchHit[]).map((h) => ({ href: `/network/${h.asn}`, title: h.name ?? "Unnamed network", sub: `${flag(h.country)} ${countryName(h.country)}`, tag: `AS${h.asn}` }));
        if (mine === seq.current) { setHits([...cs, ...ns]); setCur(0); }
      } catch { if (mine === seq.current) setHits([]); }
    }, 180);
    return () => clearTimeout(id);
  }, [q]);
  const go = (href: string) => { setQ(""); setHits(null); navigate(href); };
  const onKey = (e: React.KeyboardEvent) => {
    if (!hits?.length) return;
    if (e.key === "ArrowDown") { e.preventDefault(); setCur((c) => Math.min(hits.length - 1, c + 1)); }
    else if (e.key === "ArrowUp") { e.preventDefault(); setCur((c) => Math.max(0, c - 1)); }
    else if (e.key === "Enter") { e.preventDefault(); go(hits[cur].href); }
    else if (e.key === "Escape") setHits(null);
  };
  return (
    <div className="search">
      <label htmlFor="q">Look up a country, company or internet provider</label>
      <input id="q" value={q} autoFocus={autoFocus} autoComplete="off" placeholder="Eritrea, Google, your provider…"
        onChange={(e) => setQ(e.target.value)} onKeyDown={onKey} role="combobox" aria-expanded={!!hits} aria-controls="q-list" />
      {hits && (
        <ul id="q-list" role="listbox">
          {hits.length === 0 && <li><a>Nothing with that name. Try a shorter word.</a></li>}
          {hits.map((h, i) => (
            <li key={h.href} role="option" aria-selected={i === cur}>
              <a className={i === cur ? "cur" : ""} href={h.href} onClick={(e) => { e.preventDefault(); go(h.href); }}>
                <span><b>{h.title}</b> <span className="note">{h.sub}</span></span>
                <span className="note">{h.tag}</span>
              </a>
            </li>
          ))}
        </ul>
      )}
      <p className="note hint">Try: {TRY.map(([n, href]) => <a key={href} href={href}>{n}</a>)}</p>
    </div>
  );
}
