create table if not exists beta_feedback (
  id uuid primary key default gen_random_uuid(),
  owner_id uuid not null references tenants(owner_id) on delete cascade,
  topic text not null check (topic in ('extraction', 'installation', 'other')),
  message text not null check (char_length(message) between 10 and 1000),
  created_at timestamptz not null default now(),
  expires_at timestamptz not null default (now() + interval '30 days')
);
create index if not exists beta_feedback_owner_created on beta_feedback(owner_id, created_at);
create table if not exists beta_events_daily (
  owner_id uuid not null references tenants(owner_id) on delete cascade,
  usage_date date not null,
  event text not null check (event in ('upload_complete','glyph_accepted','build_succeeded','font_download_requested','font_used')),
  count integer not null default 1 check (count between 1 and 500),
  primary key (owner_id, usage_date, event)
);
alter table beta_feedback enable row level security;
alter table beta_events_daily enable row level security;
do $$ begin
  if exists (select 1 from pg_roles where rolname='anon') then
    revoke all on beta_feedback,beta_events_daily from anon;
  end if;
  if exists (select 1 from pg_roles where rolname='authenticated') then
    revoke all on beta_feedback,beta_events_daily from authenticated;
  end if;
end $$;
