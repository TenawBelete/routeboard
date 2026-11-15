"""Schedules the analytics jobs inside one container.

  graph job  every GRAPH_EVERY_MINUTES (default 60)  - spark-submit, reads Delta on S3
  model job  every MODEL_EVERY_MINUTES (default 360) - plain Python, reads Postgres
  names job  daily, and once at start                - downloads network names
  events job every 5 minutes                         - records bursts and surges

A failing job is logged and retried at its next slot; it never stops the runner.
The first runs start after FIRST_RUN_DELAY_MINUTES so the stream has data.
A heartbeat file lets Docker mark the container unhealthy if the loop dies.
"""

import logging
import os
import subprocess
import sys
import time
from pathlib import Path

GRAPH_EVERY = int(os.environ.get("GRAPH_EVERY_MINUTES", "60")) * 60
MODEL_EVERY = int(os.environ.get("MODEL_EVERY_MINUTES", "360")) * 60
FIRST_DELAY = int(os.environ.get("FIRST_RUN_DELAY_MINUTES", "10")) * 60
HEARTBEAT = Path("/tmp/heartbeat")
SPARK_SUBMIT = [
    "/opt/spark/bin/spark-submit", "--master=local[2]", "--driver-memory=" + os.environ.get("ANALYTICS_DRIVER_MEMORY", "1500m"),
    "--driver-java-options=-Duser.timezone=UTC", "--conf=spark.jars.ivy=/tmp/ivy",
    "--packages=" + os.environ.get("SPARK_PACKAGES", ""), "/app/graph_job.py",
]
JOBS = {
    "names": (24 * 3600, [sys.executable, "/app/names_job.py"]),   # runs first, right at start
    "events": (300, [sys.executable, "/app/events_job.py"]),
    "graph": (GRAPH_EVERY, SPARK_SUBMIT),
    "model": (MODEL_EVERY, [sys.executable, "/app/model_job.py"]),
}
logging.basicConfig(level=logging.INFO, stream=sys.stdout, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("runner")


def main() -> None:
    now = time.monotonic()
    due = {name: now + {"names": 0, "events": 120}.get(name, FIRST_DELAY) for name in JOBS}
    log.info("graph every %ds, model every %ds, first run in %ds", GRAPH_EVERY, MODEL_EVERY, FIRST_DELAY)
    while True:
        HEARTBEAT.touch()
        now = time.monotonic()
        for name, (every, cmd) in JOBS.items():
            if now < due[name]:
                continue
            log.info("%s job starting", name)
            try:
                r = subprocess.run(cmd, timeout=min(every, 3600), check=False)
                log.info("%s job finished with exit code %d", name, r.returncode)
            except subprocess.TimeoutExpired:
                log.error("%s job timed out and was killed", name)
            due[name] = time.monotonic() + every
        time.sleep(15)


if __name__ == "__main__":
    main()
