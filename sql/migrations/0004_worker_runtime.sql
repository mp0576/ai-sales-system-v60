-- Worker runtime state. No provider call belongs inside a DB transaction.
alter table outbox_events add column if not exists completed_at timestamptz;
alter table outbox_events add column if not exists dead_lettered_at timestamptz;
alter table outbox_events add column if not exists next_retry_at timestamptz;

create table if not exists dead_letter_events (
  id uuid primary key default gen_random_uuid(),
  organization_id uuid not null references organizations(id) on delete cascade,
  outbox_event_id uuid not null unique references outbox_events(id) on delete cascade,
  topic text not null,
  payload jsonb not null default '{}'::jsonb,
  attempts integer not null,
  last_error text,
  created_at timestamptz not null default now(),
  resolved_at timestamptz
);

create index if not exists idx_outbox_processing_lease on outbox_events(status, locked_at);
create index if not exists idx_outbox_retry on outbox_events(status, next_retry_at);

create or replace function public.complete_outbox(p_id uuid, p_worker_id text, p_success boolean, p_error text default null)
returns void language plpgsql security definer set search_path = public as $$
begin
  if p_success then
    update outbox_events set status='DONE', completed_at=now(), locked_at=null, locked_by=null, last_error=null
    where id=p_id and status='PROCESSING' and locked_by=p_worker_id;
  else
    update outbox_events set status='FAILED', last_error=p_error, locked_at=null, locked_by=null
    where id=p_id and status='PROCESSING' and locked_by=p_worker_id;
  end if;
end;
$$;
