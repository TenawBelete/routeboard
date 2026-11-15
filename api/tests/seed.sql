-- 30 minutes of KPIs ending 2 minutes ago, 5-min peer/origin windows, one graph run, one model run.
insert into kpi_events_1m (window_start, announcements, withdrawals, total_updates)
select date_trunc('minute', now()) - (g || ' minutes')::interval, 1000 + g, 50 + g, 1050 + 2*g
from generate_series(2, 31) g;

insert into kpi_peers_5m (window_start, peer_asn, updates, withdrawals)
select w, asn, 100 * asn / 1000, asn / 100
from (select to_timestamp(floor(extract(epoch from now()) / 300) * 300) - (g * interval '5 minutes') w
      from generate_series(1, 6) g) ws,
     (values (3333), (174), (3356), (1299)) as p(asn);

insert into kpi_origins_5m (window_start, origin_asn, announcements)
select w, asn, asn % 97
from (select to_timestamp(floor(extract(epoch from now()) / 300) * 300) - (g * interval '5 minutes') w
      from generate_series(1, 6) g) ws,
     (values (15169), (8075), (13335)) as o(asn);

insert into graph_runs (window_hours, n_nodes, n_edges, n_components, largest_component_share)
values (24, 3, 2, 1, 1.0);
insert into graph_nodes values
 (1, 3356, 0.5, 2, 1, 3, 1, 1), (1, 174, 0.3, 1, 1, 2, 2, 2), (1, 15169, 0.2, 0, 1, 1, 3, 3);
insert into graph_edges_top values (1, 174, 3356, 500), (1, 3356, 15169, 300);

insert into model_runs (model_type, label_rule, train_from, train_to, test_from, test_to,
  n_train, n_test, positive_rate, auc, precision_, recall, f1, baseline_auc, features, coefficients)
values ('logistic_regression', 'next_window_withdraw_rate >= 0.25', now()-interval '7 days', now()-interval '1 day',
  now()-interval '1 day', now(), 5000, 1000, 0.12, 0.81, 0.4, 0.6, 0.48, 0.5,
  '["rate_t0","rate_t1","rate_t2","log_updates","hour_sin","hour_cos"]', '{"rate_t0": 1.2}');
insert into model_predictions values (1, now() - interval '5 minutes', 3333, 0.9, true, null),
                                     (1, now() - interval '5 minutes', 174, 0.1, false, null);

insert into events (kind, started_at, ended_at, severity, value, magnitude, asn, data) values
 ('burst', date_trunc('minute', now()) - interval '20 minutes', date_trunc('minute', now()) - interval '17 minutes', 'alert', 2500, 24.3, null,
  '{"reporters": [{"asn": 1299, "withdrawals": 800}, {"asn": 64999, "withdrawals": 90}], "usual_per_minute": 103}'),
 ('surge', date_trunc('minute', now()) - interval '2 hours', date_trunc('minute', now()) - interval '1 hour', 'watch', 3600, 30, 15169, '{"usual_per_hour": 120}'),
 ('burst', now() - interval '9 days', now() - interval '9 days' + interval '1 minute', 'watch', 600, 5.1, null, '{}');
insert into job_runs (job, last_ok_at, detail) values ('events', now() - interval '2 minutes', 'ok'), ('names', now() - interval '3 hours', '23 names');

-- A country served by two foreign carriers: 90% through Sweden (Arelion), 10% through the US (Cogent).
insert into asn_names (asn, handle, name, country) values (64510, 'ERITEL', 'EriTel', 'ER'), (64511, 'ER-EDU', 'Eritrea Education Network', 'ER');
insert into graph_nodes values (1, 64510, 0.01, 2, 1, 3, 4, 4), (1, 64511, 0.005, 1, 0, 1, 5, 5), (1, 1299, 0.02, 0, 1, 1, 6, 6);
insert into graph_edges_top values (1, 1299, 64510, 90), (1, 174, 64510, 10), (1, 64510, 64511, 40);
insert into graph_edges_seen (src, dst, weight) select src, dst, weight from graph_edges_top on conflict do nothing;
-- a link last seen 10 days ago must not count; a thinly observed country must be flagged
insert into asn_names (asn, handle, name, country) values (64520, 'TINY', 'Tiny Telecom', 'TV'), (64521, 'OLD', 'Old Carrier', 'FJ');
insert into graph_edges_seen (src, dst, weight, last_seen) values (1299, 64520, 2, now()), (64521, 64510, 500, now() - interval '10 days');
insert into kpi_origins_5m (window_start, origin_asn, announcements)
select to_timestamp(floor(extract(epoch from now()) / 300) * 300) - (g * interval '5 minutes'), 64510, 1 from generate_series(1, 6) g;
insert into events (kind, started_at, ended_at, severity, value, magnitude, asn) values
 ('surge', now() - interval '3 days', now() - interval '3 days' + interval '1 hour', 'watch', 700, 9, 64510);
