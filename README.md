# BGP Pipeline

Real-time BGP monitoring on RIPE RIS Live: streaming ingestion, KPI
aggregation, graph analytics and ML, served through an API and a public
dashboard. Everything runs from one Docker Compose file, on a laptop or on a
single cloud server.

**Status: complete** - ingestion, streaming, lakehouse, serving database, API, graph analytics, risk model and website.

## Architecture

```
RIS Live (WebSocket)
      |
  producer  ->  Redpanda (Kafka API)  ->  Spark Structured Streaming
                                              |                 |
                                   SeaweedFS (S3 API)      Postgres (gold KPIs)
                                   bronze / silver Delta          |   ^
                                   gold/as_edges_daily         FastAPI  |
                                              |                   |     |
                                   graph job (hourly) ------------+-----+  analytics: graph + risk model
                                   risk model (6-hourly) reads Postgres
                                                              Caddy + React website
```

Storage layers (medallion):

| Layer | Where | Contents | Kept |
|---|---|---|---|
| Bronze | `s3a://lake/bronze/ris_raw` | raw RIS messages, as received | 3 days |
| Silver | `s3a://lake/silver/prefix_events` | one row per announced/withdrawn prefix, with AS path | 14 days |
| Gold (lake) | `s3a://lake/gold/as_edges_daily` | per-day AS-to-AS links with weights | forever |
| Gold (serving) | Postgres `kpi_*` tables | 1-min and 5-min KPIs the API reads | forever |

## Run it locally

Requires Docker Desktop (Apple Silicon is supported; all images are multi-arch).

```bash
make setup       # creates .env with random secrets (first time only)
make up          # build and start everything (first start: 5-10 minutes)
make health      # all services running? is the data fresh?
```

Open **http://localhost:3000**. Live numbers appear after about 2 minutes; the
graph page after ~10 minutes; the risk model after a few hours of data.
Something wrong? See [docs/TROUBLESHOOTING.md](docs/TROUBLESHOOTING.md).
Putting it on the internet: [docs/DEPLOY_HETZNER.md](docs/DEPLOY_HETZNER.md).

Other commands: `make logs`, `make spark-logs`, `make peek`, `make lake`,
`make console` (Redpanda UI, :8080), `make psql`, `make down` (keep data),
`make clean` (delete data), `make test`, `make backup`.

## Stage 2: what the Spark job does

Every 30 seconds it takes the new messages from Kafka and:

1. appends them untouched to the **bronze** Delta table (`/data/lake/bronze/ris_raw`)
2. appends one row per announced/withdrawn prefix to the **silver** Delta table
   (`/data/lake/silver/prefix_events`)
3. recomputes the 1-minute and 5-minute KPI windows that batch touched and
   **upserts** them into Postgres (`kpi_events_1m`, `kpi_peers_5m`, `kpi_origins_5m`)

Writes are replay-safe: bronze and silver use Delta idempotent writes
(`txnAppId`/`txnVersion`), and the KPI step recomputes windows from silver
instead of adding to them, so a re-run batch or a late message corrects its
window instead of double counting. The checkpoint and the lake must be deleted
together (`make clean` does both).

```bash
make spark-logs   # first start downloads connector jars, about 1-2 minutes
make kpi          # newest KPI rows
```

## Stage 2b: object storage and data lifecycle

**SeaweedFS** provides an S3 API on the same machine, so the lake is addressed
as `s3a://lake/...`. Moving to a cloud bucket later means changing
`S3_ENDPOINT` and the keys, not the Spark code. MinIO was not used because its
community edition was archived upstream in 2026.

**Nightly maintenance** (`spark/maintenance.py`, run by a thread inside the
streaming job, daily at 03:15 UTC) does three things, in this order:

1. Summarises every completed day of silver into `gold/as_edges_daily`
   (directed AS links and how many announcements carried each). This table is
   small and kept forever; it is what the graph stage reads.
2. Deletes bronze older than `RETENTION_BRONZE_DAYS` and silver older than
   `RETENTION_SILVER_DAYS`. A silver day is never deleted before it has been
   summarised, whatever its age.
3. Compacts the Delta tables (`OPTIMIZE`) and frees deleted files (`VACUUM`).

Sizing, measured on 14 Nov 2026 at `SAMPLE_EVERY=50`: about 29 MB of lake per
hour, so roughly 0.7 GB/day and ~10 GB for 14 days of silver. Sampling is the
main storage lever; see `.env.example`.

```bash
make lake          # bucket contents and total size
make maintenance   # run the nightly job now
make test          # unit tests (17), needs pyspark + pytest locally
```

### Known limits

- **Single writer per Delta table.** Delta on S3 relies on a single-driver log
  store, which is only safe with one writer process. That is why maintenance
  runs as a thread inside the streaming job instead of as a second Spark
  application. Never start a second copy of the `spark` service.
- **No replication.** SeaweedFS runs with one volume server on one disk. The
  data is public BGP data that keeps arriving, so the accepted loss on disk
  failure is history older than what Postgres holds.
- **Checkpoints are local, not in S3.** Spark's streaming checkpoint manager
  needs atomic rename and real directories, which S3-style stores do not
  provide, so it lives on the `spark-checkpoints` volume. Lake and checkpoint
  must always be reset together (`make reset-lake`).
- **`VACUUM` with a 1-hour retention** is safe only because this pipeline is
  the sole reader. Raise `VACUUM_RETAIN_HOURS` if other tools read the lake.

Unit tests live in `spark/tests`. They cover the transforms, the micro-batch
(recompute-not-add semantics) and the retention decisions. Delta and S3
operations themselves are exercised on the running stack, not in tests.

## Services

| Service | Purpose | Reachable from the host at |
|---|---|---|
| `redpanda` | Kafka-compatible broker | `localhost:19092` |
| `redpanda-init` | Creates the topic with retention caps, then exits | - |
| `producer` | RIS Live -> Kafka | - |
| `postgres` | Serving layer for the API | `localhost:5432` |
| `db-migrate` | Applies `postgres/init/*.sql` on every start, then exits | - |
| `spark` | Kafka -> Delta bronze/silver -> Postgres gold KPIs | - |
| `api` | Read-only JSON API (docs at `/api/docs`) | `localhost:8000` |
| `analytics` | Hourly graph job, six-hourly risk model, names, event detection | - |
| `live` | Kafka -> browsers, live route changes (SSE) | - |
| `web` | React site + Caddy reverse proxy | `localhost:3000` |
| `console` | Topic browser (local only, `tools` profile) | `localhost:8080` |

Inside the Compose network services address each other by name
(`redpanda:9092`, `postgres:5432`), which is why nothing changes on the server.

## Configuration

All settings live in `.env` (see `.env.example`).

| Variable | Meaning |
|---|---|
| `RIS_CLIENT` | Identifier sent to RIPE, as their usage policy asks |
| `RIS_HOSTS` | Comma-separated collectors, e.g. `rrc00,rrc03`. Empty = all |
| `SAMPLE_EVERY` | Keep 1 of every N messages |
| `TOPIC_RETENTION_MS` / `_BYTES` | Caps on how much raw data the broker keeps |

## Deploying to the server

See [docs/DEPLOY_HETZNER.md](docs/DEPLOY_HETZNER.md). In short: install Docker,
clone the repo, `make setup`, set `SITE_ADDRESS` to your domain, `make prod-up`.
Only ports 80/443 (the website) are public; Postgres, the broker, the object
store and the API are not reachable from outside.

## Stages 3-5: API, analytics, website

- **API** (`api/`): FastAPI over the gold tables. The database session is forced
  read-only, responses carry short cache headers, and `/health` reports how old
  the newest data is (`ok` / `degraded` / `down`).
- **Graph job** (`analytics/graph_job.py`, hourly): reads the last 24 h of silver,
  builds weighted directed AS links, computes PageRank, degrees, hub score and
  components with NetworkX. NetworkX instead of GraphFrames: same PageRank, no
  extra package to resolve at start-up, and the ~30k-node AS graph fits in memory.
- **Risk model** (`analytics/model_job.py`, every 6 h): logistic regression
  predicting whether a peer's next-5-minute withdrawal rate is elevated. Time-based
  split (never shuffled), compared with a no-skill baseline, and it reports
  "not enough data" instead of a number when there is too little history.
  The original notebook's AUC of 0.99 came from a random split and features that
  included the future; this version measures what it can honestly predict.
- **Names and lookup**: `analytics/names_job.py` downloads the public RIPE NCC list of network names and
  countries once a day into `asn_names`, so the site says "Google" instead of "AS15169". The API adds
  `/api/search`, `/api/network/{asn}` (one network's rank, neighbours, 24 h activity, risk) and
  `/api/briefing` (plain-language events computed from the KPI tables: bursts of withdrawals against the
  24 h median, networks far above their own usual, activity by country).
- **Live stream** (`live/`): a small service that reads the same Kafka topic as Spark (no consumer group,
  newest messages only, stateless) and pushes to browsers over Server-Sent Events: a counter every second,
  a few route changes in words, and four times a second the paths of up to 120 route changes a second, which
  drive the map animations. It also keeps the last 60 real changes per country, replayed (and labelled as a
  replay) when a country is quiet. A slow browser drops messages instead of delaying others, and
  the number of viewers is capped. The site's per-second chart, the wire and the moving dots on the map
  are driven by it; nothing on the map moves unless a real route change crossed that link.
- **Countries**: `/api/country/{cc}` groups the latest map by the country each network is registered in:
  which foreign networks and countries carry routes into it, how concentrated that is, the country's
  24 h activity and events. The page draws it on a self-hosted world map: Natural Earth 1:50m shapes adjusted by
  `web/scripts/build-world.mjs` to UN-recognised borders (Somaliland within Somalia, Northern Cyprus within
  Cyprus, Crimea within Ukraine, Western Sahara whole and separate), with a build-time check for inverted shapes.
  Links seen over the last 7 days are used, and a country with fewer than 30 observed routes shows no percentages.
  This is routing (which paths exist), not traffic volume or content, and the pages say so.
- **Events**: `analytics/events_job.py` runs every 5 minutes and records two kinds of event in the `events`
  table: a *burst* (routes closed in a minute above median + 8 x MAD of the last 24 h and at least 4 x the
  median) and a *surge* (one network at 5 x its own typical hour). Detection is idempotent (upsert on kind,
  start, network). Every event has a permanent page (`/event/<id>`), a list (`/events`) and an Atom feed
  (`/api/events.atom`).
- **Least privilege**: when `API_DB_PASSWORD` is set (`./scripts/setup.sh` adds it), the migration creates a
  `bgp_api` login with `SELECT` only, read-only transactions and a 5 s statement timeout, and the API uses it.
- **Status**: `/status` (and `/api/status`) shows when each stage last did its job: feed, stream, event
  detection, map, model, names.
- **Website** (`web/`): React + TypeScript, no UI framework, real URLs (History API), self-hosted fonts and a strict Content-Security-Policy (no third-party requests), shows
  loading / empty / error states instead of fake zeros, light and dark themes.

Tests: `make test` (Spark), and `cd api && pytest`, `cd analytics && pytest`
(these start a throwaway PostgreSQL), `cd web && npm run build`. CI runs all of them.

## Design notes

- **Raw payload is published unchanged**, so the topic is a replayable source
  of truth and parsing lives in one place (Spark).
- **Keyed by peer ASN**, so one peer's updates stay ordered within a partition.
- **Idempotent producer with `acks=all`**: retries cannot create duplicates.
- **Bounded disk**: the topic keeps 6 hours or 1 GiB per partition, whichever
  comes first.
- **Health**: the producer container reports unhealthy if it stops making
  progress for 2 minutes; `restart: unless-stopped` brings services back
  after a crash or reboot.
