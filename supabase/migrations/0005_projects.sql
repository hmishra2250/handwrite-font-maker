create table if not exists projects (
  id text primary key,
  owner_id uuid not null references tenants(owner_id) on delete cascade,
  name text not null,
  font jsonb not null,
  mode text not null check (mode in ('guided', 'markerless', 'legacy')),
  target_characters text not null,
  glyphs jsonb not null default '[]'::jsonb,
  sheet jsonb,
  last_job_id text,
  revision integer not null default 1 check (revision > 0),
  retention_expires_at timestamptz not null,
  deleted_at timestamptz,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create table if not exists tenant_project_object_refs (
  id bigserial primary key,
  owner_id uuid not null references tenants(owner_id) on delete cascade,
  bucket text not null,
  object_key text not null,
  project_id text not null references projects(id) on delete cascade,
  retention_expires_at timestamptz not null,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  unique (bucket, object_key, project_id)
);

create index if not exists projects_owner_retention_idx on projects(owner_id, retention_expires_at) where deleted_at is null;
create index if not exists projects_updated_idx on projects(owner_id, updated_at desc) where deleted_at is null;
create index if not exists tenant_project_refs_object_idx on tenant_project_object_refs(bucket, object_key);
create index if not exists tenant_project_refs_project_idx on tenant_project_object_refs(project_id);

alter table projects enable row level security;
alter table tenant_project_object_refs enable row level security;

do $$
begin
  if exists (select 1 from pg_roles where rolname = 'anon') then
    revoke all on projects, tenant_project_object_refs from anon;
  end if;
  if exists (select 1 from pg_roles where rolname = 'authenticated') then
    revoke all on projects, tenant_project_object_refs from authenticated;
  end if;
end $$;
