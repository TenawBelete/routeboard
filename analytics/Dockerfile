# Spark image + the Python libraries the analytics jobs need. The graph job
# runs under spark-submit (it reads Delta on S3); the model job is plain Python.
FROM apache/spark:3.5.3-scala2.12-java17-python3-ubuntu

USER root
ENV PIP_NO_CACHE_DIR=1 PYTHONUNBUFFERED=1 PIP_BREAK_SYSTEM_PACKAGES=1
COPY requirements.txt /tmp/requirements.txt
RUN pip install -r /tmp/requirements.txt
WORKDIR /app
COPY *.py /app/
ENV PYTHONPATH=/app
HEALTHCHECK --interval=60s --timeout=5s --start-period=60s --retries=3 \
  CMD test -n "$(find /tmp/heartbeat -mmin -2 2>/dev/null)" || exit 1
ENTRYPOINT ["python3", "/app/runner.py"]
