-- RLS: application JWT must contain sub = auth.uid(); membership is the tenant boundary.
create or replace function public.is_org_member(target_org uuid)
returns boolean language sql stable security definer set search_path = public as $$
  select exists (
    select 1 from public.organization_members m
    where m.organization_id = target_org and m.user_id = auth.uid()
  );
$$;

alter table organizations enable row level security;
alter table organization_members enable row level security;
alter table contacts enable row level security;
alter table leads enable row level security;
alter table events enable row level security;
alter table outbox_events enable row level security;
alter table actions enable row level security;

create policy organizations_member_select on organizations for select using (is_org_member(id));
create policy members_same_org_select on organization_members for select using (is_org_member(organization_id));
create policy contacts_tenant_all on contacts using (is_org_member(organization_id)) with check (is_org_member(organization_id));
create policy leads_tenant_all on leads using (is_org_member(organization_id)) with check (is_org_member(organization_id));
create policy events_tenant_all on events using (is_org_member(organization_id)) with check (is_org_member(organization_id));
create policy outbox_tenant_all on outbox_events using (is_org_member(organization_id)) with check (is_org_member(organization_id));
create policy actions_tenant_all on actions using (is_org_member(organization_id)) with check (is_org_member(organization_id));
