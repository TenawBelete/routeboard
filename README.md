# BGP Pipeline

Real-time BGP monitoring on RIPE RIS Live: streaming ingestion, KPI
aggregation, graph analytics and ML, served through an API and a public
dashboard. Everything runs from one Docker Compose file, on a laptop or on a
single cloud server.

**Status: stage 2 of 7** - broker, producer, Spark streaming job, serving database.

## Architecture

```
RIS Live (WebSocket)
      |
  producer  ->  Redpanda (Kafka API)  ->  Spark Structured Streaming   [step 2]
                                              |            |
                                     Delta lake tables   Postgres (gold KPIs)
                                     (object storage)        |
                                              |           FastAPI      [step 4]
                                      graph + ML jobs        |
                                         [step 3]         Frontend     [step 5]
```

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

Unit tests for the transforms live in `spark/tests` (need `pip install pyspark pytest`).

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
