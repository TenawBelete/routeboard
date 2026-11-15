# Troubleshooting

Run these first; they tell you most of what is wrong.

```bash
cd ~/projects/bgp-pipeline
make health          # status of every service + data freshness
docker compose ps -a # exited services show their exit code
```

| Symptom | Likely cause | Fix |
|---|---|---|
| `make: *** missing separator` | Makefile lost its tab characters (copy-paste) | Use the Makefile from the zip; never paste into it |
| `.env` errors / `variable is not set` | no `.env` yet | `make setup` |
| `Cannot connect to the Docker daemon` | Docker Desktop not running | Open Docker Desktop, wait for the whale to stop animating |
| `port is already allocated` (3000, 8000, 5432, ...) | another program uses it | Quit it, or change the left number in `docker-compose.yml` ports |
| Website shows "offline" pill | `api` not up | `docker compose logs api`; usually `db-migrate` failed, see below |
| Website says "No live numbers yet" | stream has no data yet | wait 2-3 min; check `make logs` shows `delivered=` growing and `make spark-logs` shows `batch N:` lines |
| `db-migrate` exited with error | SQL error | `docker compose logs db-migrate`; fix, then `docker compose up -d` |
| Producer log: `stream error` / `reconnecting` | network or RIPE temporarily down | nothing to do, it reconnects with back-off |
| Spark log: `ParentNotDirectoryException ... s3a://checkpoints` | old checkpoint config | `unzip -o` the latest zip, then `make reset-lake` |
| Spark container keeps restarting with `Killed` / exit 137 | out of memory | Docker Desktop > Settings > Resources > Memory 8 GB+; or lower `SPARK_DRIVER_MEMORY=1g` and `SPARK_CONTAINER_MEMORY=2g` in `.env` |
| Spark first start is very slow | downloading connector jars (1-2 min) | wait; cached afterwards in the `spark-ivy` volume |
| Graph page: "No graph analysis yet" | job starts 10 min after boot, then hourly | wait; `docker compose logs analytics` shows `graph job finished with exit code 0` |
| Graph job exit code not 0 | usually silver has no rows in the window yet | check `make lake` shows silver data; see logs |
| Networks show as "Unnamed network" | name list not downloaded yet (needs internet) | `docker compose logs analytics` should show `stored N network names`; it retries daily, or `docker compose restart analytics` |
| Looking up a small network says "Not seen today" right after this update | full map is stored from the next hourly run | wait for the next `graph job finished`, or `docker compose restart analytics` and wait 10 min |
| Home shows "The live feed is reconnecting" and never recovers | the live service cannot read the topic | open http://localhost:3000/live/health: `last_error` gives the reason and `lz4` must be `true`. If `lz4` is missing or false the old image is still running: `docker compose build --no-cache live && docker compose up -d live` |
| Home shows "The live stream is not reachable" | `live` service not running or Kafka not ready | `docker compose logs live` should show `reading ris.updates.raw`; `docker compose restart live` |
| Per-second chart moves but map dots are rare | normal: a dot appears only when a real route change crosses a link drawn on the map | nothing to fix |
| Country page says "Nothing seen today" for a real country | names not downloaded yet, or the hourly map has not run since the update | check `/status`; wait for the next map run |
| Events page stays empty | detector needs 2 hours of history, then runs every 5 min | `docker compose logs analytics` shows `events: N bursts in view`; `/status` shows when it last ran |
| API log: `password authentication failed for user "bgp_api"` | `API_DB_PASSWORD` changed after the account was created | `docker compose up -d --force-recreate db-migrate api` (the migration resets the password) |
| Model page: "No model yet" | needs a few hours of data (>= 500 labelled rows, both classes) | normal at first; the log says `not enough data yet` |
| `make lake` prints nothing | seaweedfs not healthy | `docker compose ps`, `docker compose logs seaweedfs` |
| Disk filling up | sampling too low or retention too long | raise `SAMPLE_EVERY`, lower `RETENTION_SILVER_DAYS`, run `make maintenance` |
| Everything stale after a Mac sleep | streams reconnect by themselves | wait 1-2 min; `make health` |

## Useful commands

```bash
docker compose logs --tail 50 spark      # last 50 lines of one service
docker compose restart api               # restart one service
docker compose up -d --build api         # rebuild after changing code
make kpi                                 # newest KPI rows straight from Postgres
make reset-lake                          # wipe lake + checkpoints (keeps Postgres)
make clean                               # wipe EVERYTHING and start from scratch
```

## Sending me a problem

Paste the output of `make health` and `docker compose logs --tail 40 <service>`
for the service that is not running.
