-- Stage 5: outputs of the graph and model jobs. Idempotent.

-- One row per graph computation (hourly).
CREATE TABLE IF NOT EXISTS graph_runs (
    run_id        bigserial PRIMARY KEY,
    computed_at   timestamptz NOT NULL DEFAULT now(),
    window_hours  int         NOT NULL,
    n_nodes       int         NOT NULL,
    n_edges       int         NOT NULL,
    n_components  int         NOT NULL,
    largest_component_share double precision NOT NULL
);

-- Top ASNs by PageRank and by hub score for one run. Only the latest run is
-- served; older runs are kept for a week by the maintenance job.
CREATE TABLE IF NOT EXISTS graph_nodes (
    run_id        bigint NOT NULL REFERENCES graph_runs(run_id) ON DELETE CASCADE,
    asn           bigint NOT NULL,
    pagerank      double precision NOT NULL,
    in_degree     int    NOT NULL,
    out_degree    int    NOT NULL,
    hub_score     int    NOT NULL,
    pagerank_rank int    NOT NULL,
    hub_rank      int    NOT NULL,
    PRIMARY KEY (run_id, asn)
);

-- Strongest links for the latest run (for the graph page).
CREATE TABLE IF NOT EXISTS graph_edges_top (
    run_id   bigint NOT NULL REFERENCES graph_runs(run_id) ON DELETE CASCADE,
    src      bigint NOT NULL,
    dst      bigint NOT NULL,
    weight   bigint NOT NULL,
    PRIMARY KEY (run_id, src, dst)
);

-- One row per model training run (every 6 hours).
CREATE TABLE IF NOT EXISTS model_runs (
    run_id        bigserial PRIMARY KEY,
    trained_at    timestamptz NOT NULL DEFAULT now(),
    model_type    text        NOT NULL,
    label_rule    text        NOT NULL,
    train_from    timestamptz NOT NULL,
    train_to      timestamptz NOT NULL,
    test_from     timestamptz NOT NULL,
    test_to       timestamptz NOT NULL,
    n_train       int NOT NULL,
    n_test        int NOT NULL,
    positive_rate double precision NOT NULL,
    auc           double precision,
    precision_    double precision,
    recall        double precision,
    f1            double precision,
    baseline_auc  double precision,
    features      jsonb NOT NULL,
    coefficients  jsonb
);

-- Predictions of the latest run for the most recent complete window.
CREATE TABLE IF NOT EXISTS model_predictions (
    run_id        bigint NOT NULL REFERENCES model_runs(run_id) ON DELETE CASCADE,
    window_start  timestamptz NOT NULL,
    peer_asn      bigint NOT NULL,
    probability   double precision NOT NULL,
    predicted     boolean NOT NULL,
    actual        boolean,            -- filled in by the next run, once the window is known
    PRIMARY KEY (run_id, window_start, peer_asn)
);

CREATE INDEX IF NOT EXISTS kpi_peers_5m_window_idx   ON kpi_peers_5m (window_start);
CREATE INDEX IF NOT EXISTS kpi_origins_5m_window_idx ON kpi_origins_5m (window_start);
CREATE INDEX IF NOT EXISTS model_predictions_window_idx ON model_predictions (window_start);
