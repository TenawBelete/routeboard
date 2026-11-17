// Run: node --test offline/worker.test.mjs
import test from "node:test";
import assert from "node:assert/strict";
import worker, { BUNDLE_KEY, collect } from "./worker.js";

const json = (status, body) => ({ ok: status === 200, status, json: async () => body });
const kv = (initial = null) => {
  const m = new Map(initial ? [[BUNDLE_KEY, initial]] : []);
  return { get: async (k) => m.get(k) ?? null, put: async (k, v) => { m.set(k, v); }, m };
};

test("collect sends the key and combines api and replay", async () => {
  const seen = [];
  const f = async (url, opts) => { seen.push([url, opts.headers["X-Offline-Key"]]);
    return url.endsWith("/api/offline-bundle") ? json(200, { saved_at: 5, api: { "/api/status": { overall: "ok" } } })
                                               : json(200, { ticks: [{ t: 1 }], paths: [] }); };
  const b = await collect({ ORIGIN: "https://api.example/", OFFLINE_KEY: "k" }, null, f);
  assert.deepEqual(seen.map((s) => s[0]), ["https://api.example/api/offline-bundle", "https://api.example/live/replay"]);
  assert.ok(seen.every((s) => s[1] === "k"));
  assert.equal(b.saved_at, 5);
  assert.equal(b.replay.ticks.length, 1);
});

test("an unreachable server never overwrites the saved copy", async () => {
  const store = kv(JSON.stringify({ saved_at: 1, api: {}, replay: null }));
  const realFetch = globalThis.fetch;
  globalThis.fetch = async () => json(530, {});            // Cloudflare's answer when the tunnel is down
  try { await worker.scheduled({}, { ORIGIN: "https://api.example", OFFLINE_KEY: "k", SNAPSHOT: store }); }
  finally { globalThis.fetch = realFetch; }
  assert.equal(JSON.parse(store.m.get(BUNDLE_KEY)).saved_at, 1);
});

test("if only the replay fails, the previous replay is kept", async () => {
  const f = async (url) => url.endsWith("/api/offline-bundle") ? json(200, { saved_at: 9, api: {} }) : json(500, {});
  const b = await collect({ ORIGIN: "https://x", OFFLINE_KEY: "k" }, { replay: { ticks: [{ t: 3 }] } }, f);
  assert.equal(b.saved_at, 9);
  assert.equal(b.replay.ticks[0].t, 3);
});

test("serves the bundle with CORS, 404 before anything is saved, nothing else", async () => {
  const empty = await worker.fetch(new Request("https://data.example/bundle.json"), { SNAPSHOT: kv() });
  assert.equal(empty.status, 404);
  const full = await worker.fetch(new Request("https://data.example/bundle.json"), { SNAPSHOT: kv('{"saved_at":2}') });
  assert.equal(full.status, 200);
  assert.equal(full.headers.get("access-control-allow-origin"), "*");
  assert.equal((await full.json()).saved_at, 2);
  const other = await worker.fetch(new Request("https://data.example/anything"), { SNAPSHOT: kv('{"a":1}') });
  assert.equal(other.status, 404);
});
