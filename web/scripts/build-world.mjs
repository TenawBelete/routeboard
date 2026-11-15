// Generates public/world.json: country shapes keyed by ISO alpha-2 and a centre point for each.
// Source: Natural Earth 1:50m via the world-atlas package. Run: node scripts/build-world.mjs
//
// Natural Earth draws some de-facto boundaries. This site shows UN-recognised borders, so:
//   - Somaliland is merged into Somalia
//   - Northern Cyprus is merged into Cyprus
//   - Crimea is moved from Russia to Ukraine
//   - Western Sahara is drawn whole and separate from Morocco
//   - Kosovo is kept as its own shape (code XK); the Siachen Glacier area is drawn neutral
// The map is for orientation and takes no position on disputed borders.
import { readFileSync, writeFileSync, mkdirSync } from "node:fs";
import { feature, merge } from "topojson-client";
import { geoCentroid, geoArea } from "d3-geo";
import iso from "i18n-iso-countries";

const topo = JSON.parse(readFileSync(new URL("../node_modules/world-atlas/countries-50m.json", import.meta.url)));
const geoms = topo.objects.countries.geometries;
const byName = (n) => { const g = geoms.find((x) => x.properties.name === n); if (!g) throw new Error(`missing ${n}`); return g; };
const a2 = (id) => (id == null ? undefined : iso.numericToAlpha2(String(id).padStart(3, "0")));
const round = (n) => Math.round(n * 100) / 100;
const polys = (g) => (g.type === "Polygon" ? [g.coordinates] : g.coordinates);

const MERGE = { Somalia: "Somaliland", Cyprus: "N. Cyprus" };
const SKIP = new Set(["Somaliland", "N. Cyprus", "Indian Ocean Ter."]);
const shapes = new Map();   // cc -> list of polygons

for (const g of geoms) {
  const name = g.properties.name;
  if (SKIP.has(name)) continue;
  const cc = name === "Kosovo" ? "XK" : name === "Siachen Glacier" ? "_disputed" : a2(g.id);
  if (!cc) throw new Error(`no code for ${name}`);
  const geometry = MERGE[name] ? merge(topo, [g, byName(MERGE[name])]) : feature(topo, g).geometry;
  // Several source features can share one country code (Australia and its Ashmore & Cartier Islands), so add, never replace.
  shapes.set(cc, [...(shapes.get(cc) ?? []), ...polys(geometry)]);
}

// Western Sahara: every resolution of the source gives Morocco the part it controls. The UN lists the
// territory whole, and its northern border is the parallel 27 deg 40' N. So Morocco and W. Sahara are merged
// into one outline and cut along that parallel: north is Morocco, south is Western Sahara.
{
  const LAT = 27.6667;
  const merged = polys(merge(topo, [byName("Morocco"), byName("W. Sahara")]));
  const clip = (ring, keepNorth) => {            // Sutherland-Hodgman against one horizontal line
    const inside = ([, y]) => (keepNorth ? y >= LAT : y <= LAT), out = [];
    for (let i = 0; i < ring.length - 1; i++) {
      const p = ring[i], q = ring[i + 1], pi = inside(p), qi = inside(q);
      if (pi) out.push(p);
      if (pi !== qi) out.push([p[0] + ((LAT - p[1]) / (q[1] - p[1])) * (q[0] - p[0]), LAT]);
    }
    if (out.length >= 3) out.push(out[0]);
    return out;
  };
  const part = (keepNorth) => merged.map((poly) => [clip(poly[0], keepNorth)]).filter((poly) => poly[0].length >= 4);
  shapes.set("MA", part(true));
  shapes.set("EH", part(false));
}

// Crimea: the one Russian polygon centred on the peninsula.
const inCrimea = (p) => { const [lon, lat] = geoCentroid({ type: "Polygon", coordinates: p }); return lon > 32 && lon < 37 && lat > 44 && lat < 46.5; };
const crimea = shapes.get("RU").filter(inCrimea);
if (crimea.length !== 1) throw new Error(`expected exactly one Crimea polygon, found ${crimea.length}`);
shapes.set("RU", shapes.get("RU").filter((p) => !inCrimea(p)));
shapes.set("UA", [...shapes.get("UA"), ...crimea]);

// Centre = centre of the largest polygon, so France sits in Europe and the USA in North America.
const centres = {};
const out = [];
for (const [cc, ps] of shapes) {
  // 0.1 degree is about one pixel at the closest zoom this site uses; it cuts the file to a third.
  const r1 = (n) => Math.round(n * 10) / 10;
  const thin = (ring) => { const o = []; for (const [x, y] of ring) { const q = [r1(x), r1(y)]; if (!o.length || o[o.length - 1][0] !== q[0] || o[o.length - 1][1] !== q[1]) o.push(q); } return o; };
  const rounded = ps.map((p) => p.map(thin).filter((ring) => ring.length >= 4)).filter((p) => p.length);
  // Rounding can flip the winding of a tiny island, which a spherical renderer reads as "everything except
  // this island". Put any such ring back the right way round and drop islets that collapsed to nothing.
  for (let i = rounded.length - 1; i >= 0; i--) {
    if (geoArea({ type: "Polygon", coordinates: rounded[i] }) > 2 * Math.PI) rounded[i] = rounded[i].map((ring) => [...ring].reverse());
    const a = geoArea({ type: "Polygon", coordinates: rounded[i] });
    if (a > 2 * Math.PI || a < 1e-9) rounded.splice(i, 1);
  }
  if (!rounded.length) rounded.push(ps[0].map((ring) => ring.map(([x, y]) => [round(x), round(y)])));   // a tiny island state keeps its shape
  out.push({ type: "Feature", id: cc, properties: {}, geometry: { type: "MultiPolygon", coordinates: rounded } });
  if (cc.startsWith("_")) continue;
  let best = ps[0], area = -1;
  for (const p of ps) { const a = geoArea({ type: "Polygon", coordinates: p }); if (a > area) { area = a; best = p; } }
  centres[cc] = geoCentroid({ type: "Polygon", coordinates: best }).map(round);
}
// Russia's largest polygon is centred in Siberia; its networks and people are in the west, so lines
// to "Russia" should point at Moscow rather than the middle of the taiga.
centres.RU = [37.62, 55.75];
mkdirSync(new URL("../public/", import.meta.url), { recursive: true });
writeFileSync(new URL("../public/world.json", import.meta.url), JSON.stringify({ shapes: out, centres }));
const bad = out.filter((f) => geoArea(f) > 2 * Math.PI).map((f) => f.id);
if (bad.length) throw new Error(`inverted shapes: ${bad}`);
console.log(`shapes: ${out.length}, centres: ${Object.keys(centres).length}`);
