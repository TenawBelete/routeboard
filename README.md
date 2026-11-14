# BGP Pipeline

Real-time BGP monitoring on RIPE RIS Live: streaming ingestion, KPI
aggregation, graph analytics and ML, served through an API and a public
dashboard. Everything runs from one Docker Compose file, on a laptop or on a
single cloud server.

**Status: stage 2b of 7** - broker, producer, object storage, Spark streaming job, serving database, nightly maintenance.

## Architecture

```
RIS Live (WebSocket)
      |
  producer  ->  Redpanda (Kafka API)  ->  Spark Structured Streaming
                                              |                 |
                                   SeaweedFS (S3 API)      Postgres (gold KPIs)
                                   bronze / silver Delta          |
                                   gold/as_edges_daily         FastAPI      [stage 3]
                                              |                   |
                                   nightly maintenance         Frontend     [stage 4]
                                   graph + ML jobs  [stage 5]
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
cp .env.example .env        # then set RIS_CLIENT to something that names you
make up                     # build and start
make logs                   # watch the producer; a stats line every 30s
make peek                   # print 3 messages from the topic
```

Expected producer log:

```
subscribed (hosts=all, sample_every=50)
received=41250 produced=825 delivered=825 failed=0 skipped=0
```

Other commands: `make console` (web UI at http://localhost:8080), `make psql`,
`make down` (stop, keep data), `make clean` (stop and delete data).

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

**Nightly maintenance** (`spark/maintenance.py`, scheduled by the `scheduler`
container, default 03:15 UTC) does three things, in this order:

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
  store here. Only the streaming job writes bronze/silver and only maintenance
  writes `as_edges_daily`; maintenance also deletes from bronze/silver while the
  stream appends to them, which Delta's optimistic concurrency allows because
  they touch different files. Running two copies of either job would corrupt
  the log.
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

1. Install Docker on the server and clone this repo.
2. Create `.env` there with a strong `POSTGRES_PASSWORD`.
3. `docker compose up -d --build`

No ports are exposed publicly: every port binds to `127.0.0.1`. Public HTTPS
access is added with a reverse proxy in step 6.

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
