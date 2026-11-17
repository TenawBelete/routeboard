-- Fast network search (security review, item 1): "lower(name) like '%text%'" scanned the whole table.
-- A trigram index answers contains-searches from the index; a pattern index answers handle prefixes.
-- pg_trgm is a trusted extension (PostgreSQL 13+), part of the standard image. Safe to run again.
create extension if not exists pg_trgm;
create index if not exists asn_names_name_trgm on asn_names using gin (lower(name) gin_trgm_ops);
create index if not exists asn_names_handle_prefix on asn_names (lower(handle) text_pattern_ops);
