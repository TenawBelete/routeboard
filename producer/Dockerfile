FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
WORKDIR /app

COPY requirements.txt .
RUN pip install -r requirements.txt

COPY producer.py .

RUN useradd --create-home app
USER app

# Healthy = the producer wrote its heartbeat file in the last 2 minutes.
HEALTHCHECK --interval=30s --timeout=5s --start-period=60s --retries=3 \
  CMD python -c "import os,sys,time; sys.exit(0 if time.time()-os.path.getmtime('/tmp/heartbeat')<120 else 1)"

CMD ["python", "producer.py"]
