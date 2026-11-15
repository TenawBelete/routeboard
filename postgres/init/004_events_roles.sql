-- Permanent record of notable events, and a least-privilege account for the API. Idempotent.

-- One row per detected disruption. Written by analytics/events_job.py every 5 minutes.
-- The wording shown on the site is produced by the API from these facts, so it can
-- improve without rewriting history.
CREATE TABLE IF NOT EXISTS events (
    id          bigserial PRIMARY KEY,
    kind        text NOT NULL CHECK (kind IN ('burst', 'surge')),
    started_at  timestamptz NOT NULL,
    ended_at    timestamptz NOT NULL,
    severity    text NOT NULL CHECK (severity IN ('alert', 'watch')),
    value       bigint NOT NULL,              -- burst: peak routes closed in a minute; surge: route changes in the hour
    magnitude   double precision NOT NULL,    -- how many times the usual
    asn         bigint,                       -- surge only: the network concerned
    data        jsonb NOT NULL DEFAULT '{}',  -- e.g. {"reporters": [{"asn": 1299, "withdrawals": 812}]}
    detected_at timestamptz NOT NULL DEFAULT now()
);
CREATE UNIQUE INDEX IF NOT EXISTS events_key_idx ON events (kind, started_at, (coalesce(asn, 0)));
CREATE INDEX IF NOT EXISTS events_started_idx ON events (started_at DESC);

-- Heartbeat of the background jobs, shown on the public status page.
CREATE TABLE IF NOT EXISTS job_runs (
    job         text PRIMARY KEY,
    last_ok_at  timestamptz,
    last_run_at timestamptz NOT NULL DEFAULT now(),
    detail      text
);

-- Read-only login for the API. Created only when a password is supplied
-- (db-migrate passes -v api_pw=... when API_DB_PASSWORD is set in .env).
\if :{?api_pw}
SELECT format('CREATE ROLE bgp_api LOGIN PASSWORD %L', :'api_pw')
 WHERE NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'bgp_api') \gexec
SELECT format('ALTER ROLE bgp_api LOGIN PASSWORD %L', :'api_pw') \gexec
SELECT format('GRANT CONNECT ON DATABASE %I TO bgp_api', current_database()) \gexec
GRANT USAGE ON SCHEMA public TO bgp_api;
GRANT SELECT ON ALL TABLES IN SCHEMA public TO bgp_api;
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT ON TABLES TO bgp_api;
ALTER ROLE bgp_api SET default_transaction_read_only = on;
ALTER ROLE bgp_api SET statement_timeout = '5s';
\endif
