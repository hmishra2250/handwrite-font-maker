create extension if not exists pgcrypto;

alter table jobs add column if not exists owner_id uuid;
alter table jobs add column if not exists delete_requested_at timestamptz;

create table if not exists tenants (
  owner_id uuid primary key,
  status text not null default 'active' check (status in ('active', 'disabled')),
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create table if not exists tenant_daily_usage (
  owner_id uuid not null references tenants(owner_id) on delete cascade,
  usage_date date not null,
  uploads_count integer not null default 0 check (uploads_count >= 0),
  upload_bytes bigint not null default 0 check (upload_bytes >= 0),
  previews_count integer not null default 0 check (previews_count >= 0),
  builds_count integer not null default 0 check (builds_count >= 0),
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  primary key (owner_id, usage_date)
);

create table if not exists tenant_objects (
  id bigserial primary key,
  owner_id uuid not null references tenants(owner_id) on delete cascade,
  bucket text not null,
  object_key text not null,
  kind text not null,
  content_type text not null,
  size_bytes bigint not null default 0 check (size_bytes >= 0),
  job_id text,
  status text not null default 'registered' check (status in ('registered', 'uploading', 'uploaded', 'delete_pending', 'deleted', 'delete_failed')),
  retention_expires_at timestamptz not null,
  delete_attempts integer not null default 0 check (delete_attempts >= 0),
  last_delete_error text,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  unique (bucket, object_key)
);

create table if not exists tenant_object_job_refs (
  id bigserial primary key,
  owner_id uuid not null references tenants(owner_id) on delete cascade,
  bucket text not null,
  object_key text not null,
  job_id text not null references jobs(id) on delete cascade,
  retention_expires_at timestamptz not null,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  unique (bucket, object_key, job_id)
);

create index if not exists tenant_objects_owner_key_idx on tenant_objects(owner_id, bucket, object_key);
create index if not exists tenant_objects_job_idx on tenant_objects(job_id);
create index if not exists tenant_objects_retention_idx on tenant_objects(retention_expires_at, status);
create index if not exists tenant_object_refs_object_idx on tenant_object_job_refs(bucket, object_key);
create index if not exists tenant_object_refs_job_idx on tenant_object_job_refs(job_id);
create index if not exists tenant_usage_owner_date_idx on tenant_daily_usage(owner_id, usage_date);
create index if not exists jobs_owner_retention_idx on jobs(owner_id, retention_expires_at);

alter table tenant_objects add column if not exists delete_not_before timestamptz;
alter table tenant_objects add column if not exists next_delete_attempt_at timestamptz;

alter table tenant_objects drop constraint if exists tenant_objects_status_check;
alter table tenant_objects add constraint tenant_objects_status_check
  check (status in ('registered', 'uploading', 'uploaded', 'delete_pending', 'deleted', 'delete_failed'));

alter table jobs enable row level security;
alter table job_warnings enable row level security;
alter table job_artifacts enable row level security;
alter table tenants enable row level security;
alter table tenant_daily_usage enable row level security;
alter table tenant_objects enable row level security;
alter table tenant_object_job_refs enable row level security;

do $$
begin
  if exists (select 1 from pg_roles where rolname = 'anon') then
    revoke all on jobs, job_warnings, job_artifacts, tenants, tenant_daily_usage, tenant_objects, tenant_object_job_refs from anon;
  end if;
  if exists (select 1 from pg_roles where rolname = 'authenticated') then
    revoke all on jobs, job_warnings, job_artifacts, tenants, tenant_daily_usage, tenant_objects, tenant_object_job_refs from authenticated;
  end if;
end $$;
