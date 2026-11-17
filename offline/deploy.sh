#!/usr/bin/env bash
# One-time setup and later updates of the offline saver. Run from anywhere:
#   bash ~/projects/bgp-pipeline/offline/deploy.sh
set -euo pipefail
cd "$(dirname "$0")"
W="npx --yes wrangler@4"

echo "== 1/4 Cloudflare login (a browser window opens the first time)"
$W whoami >/dev/null 2>&1 || $W login

echo "== 2/4 Storage for the saved copy (Workers KV)"
if grep -q REPLACE_WITH_KV_ID wrangler.toml; then
  out=$($W kv namespace create SNAPSHOT 2>&1) || { echo "$out"; exit 1; }
  id=$(printf '%s' "$out" | grep -oE '[0-9a-f]{32}' | head -1)
  [ -n "$id" ] || { echo "Could not read the KV id from:"; echo "$out"; exit 1; }
  sed -i.bak "s/REPLACE_WITH_KV_ID/$id/" wrangler.toml && rm -f wrangler.toml.bak
  echo "   created, id $id"
else
  echo "   already set up"
fi

echo "== 3/4 Shared key (taken from your .env, never printed)"
key=$(grep -E '^OFFLINE_KEY=' ../.env | cut -d= -f2- || true)
[ -n "$key" ] || { echo "No OFFLINE_KEY in ../.env. Run: make setup"; exit 1; }
printf '%s' "$key" | $W secret put OFFLINE_KEY >/dev/null
echo "   stored as a Worker secret"

echo "== 4/4 Deploy"
$W deploy
echo
echo "Done. In about 2 minutes this should show saved data:  curl -s https://data.butenai.com/bundle.json | head -c 200"
