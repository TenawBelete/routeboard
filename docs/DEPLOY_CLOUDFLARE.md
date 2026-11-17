# Public site on Cloudflare, server on your Mac

The website stays reachable even when the Mac is off. When the server is down, visitors see the
data saved a few minutes earlier and a replay of the 10 minutes before it stopped, under a clear
"The live server is paused" banner. It switches back to live data by itself.

```
visitor ──> butenai.com        Cloudflare Pages   the website itself (always on, free)
        ──> api.butenai.com    Cloudflare tunnel  your Mac: /api and /live
        ──> data.butenai.com   Cloudflare Worker  the saved copy, refreshed every 2 minutes
```

Everything here is on Cloudflare's free plan. Allow about 30 minutes the first time.

## 1. Settings on the Mac

```bash
cd ~/projects/bgp-pipeline
make setup                      # adds OFFLINE_KEY to .env (keeps everything else)
cat >> .env <<'ENV'
SITE_URL=https://butenai.com
CORS_ORIGINS=https://butenai.com,https://www.butenai.com
API_DOCS=false
ENV
docker compose up -d --build
```

## 2. Move the tunnel to api.butenai.com

```bash
cloudflared tunnel route dns routeboard api.butenai.com
nano ~/.cloudflared/config.yml
```
Change both `hostname:` lines so only this one remains above the final `http_status:404` line:
```yaml
  - hostname: api.butenai.com
    service: http://localhost:3000
```
Then restart the background service:
```bash
launchctl kickstart -k gui/$(id -u)/com.cloudflare.cloudflared
curl -s https://api.butenai.com/health
```
You should see `{"status":"ok", ...}` (or `"degraded"` for a minute after a restart).
If `launchctl` says the service is not found, reinstall it: `cloudflared service uninstall && cloudflared service install`.

## 3. The website on Cloudflare Pages

1. In Cloudflare: **DNS → Records**. Delete the two tunnel records for `butenai.com` and
   `www` (type CNAME, target ends in `cfargotunnel.com`). Keep `api`.
2. **Workers & Pages → Create → Pages → Connect to Git**, choose `TenawBelete/routeboard`.
3. Build settings:
   - Framework preset: **None**
   - Build command: `npm ci && npm run build:pages`
   - Build output directory: `dist`
   - Root directory: `web`
   - Environment variables:
     `VITE_API_BASE` = `https://api.butenai.com`,
     `VITE_OFFLINE_URL` = `https://data.butenai.com/bundle.json`,
     `NODE_VERSION` = `22`
4. **Save and Deploy**. When it finishes: **Custom domains → Set up a domain** → `butenai.com`,
   then again for `www.butenai.com`.

From now on every `git push` to `main` rebuilds the site automatically.

## 4. The offline saver (Worker)

```bash
bash ~/projects/bgp-pipeline/offline/deploy.sh
```
A browser window asks you to allow Wrangler (Cloudflare's tool) the first time. The script creates
the storage, copies `OFFLINE_KEY` from your `.env` into Cloudflare as a secret, and deploys. Two
minutes later:
```bash
curl -s https://data.butenai.com/bundle.json | head -c 120
```
should start with `{"version":1,"saved_at":...`.

## 5. Cache rule (security review, item 1)

**Caching → Cache Rules → Create rule**: name `API`, when *Hostname equals* `api.butenai.com`
**and** *URI Path starts with* `/api/`, then **Eligible for cache**, Edge TTL **Use cache-control
header if present**. Deploy. Identical requests within 5 seconds are then answered by Cloudflare.

The two security rules you already have (Block scanners, Limit API floods) apply to every
`butenai.com` name, including `api.`, so nothing changes there.

## 6. Test the offline mode

1. Open https://butenai.com and leave it open.
2. On the Mac: `docker compose stop api live`.
3. Within about 30 seconds the black-and-yellow banner appears, the counters keep moving (replay),
   and the other pages show the saved numbers.
4. `docker compose start api live`. Within 10 seconds the banner disappears and live data returns.

## Limits worth knowing

- The saved copy is at most 2 minutes old when the server stops, and only the pages listed in
  `OFFLINE_PATHS` (api/app/main.py) plus whatever visitors opened in the last 15 minutes are in it.
  Other network or country pages show "cannot reach the API" while the server is down.
- Word-by-word route messages are not replayed, only the counts and the map dots.
- Search does not work while the server is down.
- Free-plan budget used: 720 Worker runs and 720 KV writes a day (limit 1,000 writes).
