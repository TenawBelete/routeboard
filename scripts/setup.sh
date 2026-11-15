#!/usr/bin/env bash
# Creates .env with fresh random secrets. Safe to run again: an existing .env is
# never overwritten, only extended with settings added by newer versions.
set -euo pipefail
cd "$(dirname "$0")/.."

rand() { LC_ALL=C tr -dc 'A-Za-z0-9' </dev/urandom | head -c 32; }

if [ -f .env ]; then
  # Existing install: keep everything, only add settings introduced by newer versions.
  if ! grep -q '^API_DB_PASSWORD=' .env; then
    printf '\n# Read-only database account for the API\nAPI_DB_PASSWORD=%s\n' "$(rand)" >> .env
    echo "Added API_DB_PASSWORD to .env."
  else
    echo ".env is up to date."
  fi
  exit 0
fi

name="${1:-}"
if [ -z "$name" ]; then
  read -r -p "A short name for you or the project (letters, digits, dashes), e.g. tenaw-bgp: " name
fi
name="$(echo "$name" | tr -c 'A-Za-z0-9-\n' '-' | sed 's/-*$//')"
[ -n "$name" ] || name="bgp-pipeline"

cp .env.example .env
sed -i.bak \
  -e "s|^RIS_CLIENT=.*|RIS_CLIENT=bgp-pipeline-$name|" \
  -e "s|^POSTGRES_PASSWORD=.*|POSTGRES_PASSWORD=$(rand)|" \
  -e "s|^S3_SECRET_KEY=.*|S3_SECRET_KEY=$(rand)|" \
  -e "s|^API_DB_PASSWORD=.*|API_DB_PASSWORD=$(rand)|" .env
rm -f .env.bak
echo "Created .env (secrets generated; never commit this file)."
