-- A longer memory of links than one 24-hour map. Idempotent.
-- Small countries appear in only a handful of sampled messages a day, so the country
-- pages read links seen over the last 7 days instead of today's map alone.
-- `weight` is the largest 24-hour count seen for the link (never a sum of overlapping windows).
CREATE TABLE IF NOT EXISTS graph_edges_seen (
    src       bigint NOT NULL,
    dst       bigint NOT NULL,
    weight    bigint NOT NULL,
    last_seen timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (src, dst)
);
CREATE INDEX IF NOT EXISTS graph_edges_seen_dst_idx ON graph_edges_seen (dst);

-- Start from whatever maps already exist, so the pages work before the next hourly run.
INSERT INTO graph_edges_seen (src, dst, weight, last_seen)
SELECT e.src, e.dst, max(e.weight), max(r.computed_at)
FROM graph_edges_top e JOIN graph_runs r ON r.run_id = e.run_id
GROUP BY e.src, e.dst
ON CONFLICT (src, dst) DO NOTHING;
