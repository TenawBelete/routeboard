// Routeboard offline saver (Cloudflare Worker, free plan).
//
// Every two minutes it asks the server for a "bundle": the answers the pages need plus the last
// 10 minutes of real route changes. It keeps the newest good bundle in Workers KV and serves it at
// https://data.butenai.com/bundle.json. When the server (the Mac) stops, the website falls back to
// this saved copy and says so on screen. If the server cannot be reached, the old bundle is kept,
// never overwritten with an error.
//
// Free-plan budget: 720 cron runs and 720 KV writes a day (limit 1,000 writes), two requests each.

export const BUNDLE_KEY = "bundle";

const CORS = {
  "Access-Control-Allow-Origin": "*",          // public, read-only data; no cookies are involved
  "Access-Control-Allow-Methods": "GET, OPTIONS",
  "Access-Control-Max-Age": "86400",
};

/** Fetch a fresh bundle from the origin. Throws if the API part cannot be fetched. */
export async function collect(env, previous = null, fetchFn = fetch) {
  const base = String(env.ORIGIN || "").replace(/\/$/, "");
  const headers = { "X-Offline-Key": env.OFFLINE_KEY || "", "User-Agent": "routeboard-offline-saver/1" };
  const [api, live] = await Promise.allSettled([
    fetchFn(`${base}/api/offline-bundle`, { headers }),
    fetchFn(`${base}/live/replay`, { headers }),
  ]);
  if (api.status !== "fulfilled" || !api.value.ok) {
    throw new Error(`api not reachable (${api.status === "fulfilled" ? api.value.status : api.reason})`);
  }
  const a = await api.value.json();
  let replay = previous?.replay ?? null;                 // keep the last good replay if only that part failed
  if (live.status === "fulfilled" && live.value.ok) replay = await live.value.json();
  return { version: 1, saved_at: a.saved_at, api: a.api, replay };
}

export default {
  async scheduled(_event, env) {
    let previous = null;
    try { previous = JSON.parse((await env.SNAPSHOT.get(BUNDLE_KEY)) || "null"); } catch { previous = null; }
    try {
      const bundle = await collect(env, previous);
      await env.SNAPSHOT.put(BUNDLE_KEY, JSON.stringify(bundle));
    } catch (e) {
      console.log("origin unreachable; keeping the last saved bundle:", String(e));
    }
  },

  async fetch(request, env) {
    if (request.method === "OPTIONS") return new Response(null, { status: 204, headers: CORS });
    const url = new URL(request.url);
    if (request.method !== "GET" || url.pathname !== "/bundle.json") {
      return new Response("not found", { status: 404, headers: CORS });
    }
    const body = await env.SNAPSHOT.get(BUNDLE_KEY, { cacheTtl: 60 });
    if (!body) {
      return new Response(JSON.stringify({ detail: "nothing saved yet" }), {
        status: 404, headers: { ...CORS, "Content-Type": "application/json" },
      });
    }
    return new Response(body, {
      headers: {
        ...CORS,
        "Content-Type": "application/json",
        "Cache-Control": "public, max-age=60",
        "X-Content-Type-Options": "nosniff",
      },
    });
  },
};
