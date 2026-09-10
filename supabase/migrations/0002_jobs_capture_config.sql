alter table jobs
  add column if not exists capture_config jsonb;

comment on column jobs.capture_config is
  'Versioned alpha capture contract JSON. Null preserves legacy ArUco v1 jobs.';
