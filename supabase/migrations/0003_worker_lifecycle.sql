-- Additive: old local records retain a nullable owner; authenticated routes deny ownerless jobs.
alter table jobs add column if not exists owner_id uuid;
alter table jobs add column if not exists attempt_id text;
alter table jobs add column if not exists attempt_count integer not null default 0;
create index if not exists jobs_owner_idx on jobs(owner_id, created_at);
create index if not exists jobs_running_lease_idx on jobs(lease_expires_at) where status='running';
