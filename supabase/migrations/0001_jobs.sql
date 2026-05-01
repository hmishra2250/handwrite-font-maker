create table if not exists jobs (
  id text primary key,
  status text not null check (status in ('queued', 'running', 'succeeded', 'failed', 'expired')),
  stage text not null,
  font_name text not null,
  family_name text not null,
  style_name text not null default 'Regular',
  input_bucket text not null,
  input_path text not null,
  input_content_type text not null,
  input_size_bytes bigint not null,
  error_code text,
  error_message text,
  error_retryable boolean,
  error_details jsonb not null default '{}'::jsonb,
  lease_owner text,
  lease_expires_at timestamptz,
  retention_expires_at timestamptz not null,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  completed_at timestamptz
);

create table if not exists job_warnings (
  id bigserial primary key,
  job_id text not null references jobs(id) on delete cascade,
  code text not null,
  glyph text,
  message text not null,
  severity text not null default 'warning',
  details jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now()
);

create table if not exists job_artifacts (
  id bigserial primary key,
  job_id text not null references jobs(id) on delete cascade,
  kind text not null,
  label text not null,
  bucket text not null,
  path text not null,
  content_type text not null,
  size_bytes bigint not null,
  created_at timestamptz not null default now()
);

create index if not exists jobs_status_created_idx on jobs(status, created_at);
create index if not exists jobs_retention_expires_idx on jobs(retention_expires_at);
