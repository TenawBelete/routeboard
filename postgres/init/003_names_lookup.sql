-- Human names for networks, and indexes for per-network lookups. Idempotent.

-- One row per network (autonomous system). Filled daily by analytics/names_job.py
-- from the public RIPE NCC list; `name` is the display name shown on the site.
CREATE TABLE IF NOT EXISTS asn_names (
    asn        bigint PRIMARY KEY,
    handle     text NOT NULL,          -- registry handle, e.g. GOOGLE
    name       text NOT NULL,          -- display name, e.g. Google
    country    text,                   -- ISO 3166 alpha-2, e.g. US
    updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS asn_names_name_idx ON asn_names (lower(name) text_pattern_ops);

-- A few names so the site reads well before the first download finishes.
INSERT INTO asn_names (asn, handle, name, country) VALUES
 (174,'COGENT-174','Cogent','US'), (701,'UUNET','Verizon','US'), (1273,'CW','Vodafone','GB'),
 (1299,'TWELVE99','Arelion','SE'), (2914,'NTT-DATA-2914','NTT','US'), (3257,'GTT-BACKBONE','GTT','US'),
 (3320,'DTAG','Deutsche Telekom','DE'), (3333,'RIPE-NCC-AS','RIPE NCC','NL'), (3356,'LEVEL3','Lumen','US'),
 (3491,'BTN-ASN','PCCW Global','US'), (5511,'OPENTRANSIT','Orange','FR'), (6453,'AS6453','Tata Communications','US'),
 (6461,'ZAYO-6461','Zayo','US'), (6762,'SEABONE-NET','Telecom Italia Sparkle','IT'), (6939,'HURRICANE','Hurricane Electric','US'),
 (7018,'ATT-INTERNET4','AT&T','US'), (8075,'MICROSOFT-CORP-MSN-AS-BLOCK','Microsoft','US'), (12956,'TELXIUS','Telxius','ES'),
 (13335,'CLOUDFLARENET','Cloudflare','US'), (15169,'GOOGLE','Google','US'), (16509,'AMAZON-02','Amazon','US'),
 (20940,'AKAMAI-ASN1','Akamai','NL'), (32934,'FACEBOOK','Meta','US')
ON CONFLICT (asn) DO NOTHING;

-- Per-network lookups: "everything about AS15169".
CREATE INDEX IF NOT EXISTS kpi_origins_5m_asn_idx ON kpi_origins_5m (origin_asn, window_start);
CREATE INDEX IF NOT EXISTS kpi_peers_5m_asn_idx   ON kpi_peers_5m (peer_asn, window_start);
CREATE INDEX IF NOT EXISTS graph_edges_top_dst_idx ON graph_edges_top (run_id, dst);
CREATE INDEX IF NOT EXISTS model_predictions_peer_idx ON model_predictions (peer_asn, run_id);
