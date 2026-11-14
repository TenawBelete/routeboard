-- Make naive timestamps written by Spark (UTC) read back correctly.
DO $$ BEGIN
  EXECUTE format('ALTER DATABASE %I SET timezone TO ''UTC''', current_database());
END $$;

-- Serving layer: small "gold" tables the API reads.
-- Spark upserts into these, so every table has a primary key on its window.

CREATE TABLE IF NOT EXISTS kpi_events_1m (
    window_start   timestamptz PRIMARY KEY,
    announcements  bigint NOT NULL,
    withdrawals    bigint NOT NULL,
    total_updates  bigint NOT NULL,
    updated_at     timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS kpi_peers_5m (
    window_start   timestamptz NOT NULL,
    peer_asn       bigint      NOT NULL,
    updates        bigint      NOT NULL,
    withdrawals    bigint      NOT NULL,
    updated_at     timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (window_start, peer_asn)
);

CREATE TABLE IF NOT EXISTS kpi_origins_5m (
    window_start   timestamptz NOT NULL,
    origin_asn     bigint      NOT NULL,
    announcements  bigint      NOT NULL,
    updated_at     timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (window_start, origin_asn)
);
