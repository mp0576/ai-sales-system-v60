-- Atomically claim a batch for a worker. Stale PROCESSING rows can be reclaimed by lease timeout.
create or replace function public.claim_outbox(batch_size integer, worker_id text, lease_seconds integer default 120)
returns setof outbox_events language plpgsql security definer set search_path = public as $$
begin
  return query
  with candidates as (
    select id from outbox_events
    where (status = 'PENDING' and available_at <= now())
       or (status = 'PROCESSING' and locked_at < now() - make_interval(secs => lease_seconds))
    order by available_at, created_at
    for update skip locked limit batch_size
  )
  update outbox_events o
     set status = 'PROCESSING', locked_at = now(), locked_by = worker_id, attempts = attempts + 1
   where o.id in (select id from candidates)
  returning o.*;
end;
$$;
