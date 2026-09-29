-- NOTE: This SQL script must be run manually in the Supabase SQL Editor,
-- as changes in this repository will not apply automatically to the database.
-- If you are updating check_and_log_send, this script must be re-run manually
-- in Supabase's SQL Editor to take effect, since it replaces the existing function.

create table if not exists public.send_logs (
  id bigint generated always as identity primary key,
  ip_address text,
  receiver text,
  file_name text,
  created_at timestamptz default now()
);

-- Atomic function to check rate limits (5 sends / 3 sec / IP),
-- check daily cap (400 sends / day UTC), and record the send log in a single transaction.
-- Concurrency-safe via pg_advisory_xact_lock per IP.
create or replace function check_and_log_send(
  p_ip text,
  p_receiver text,
  p_file_name text
) returns boolean
language plpgsql
security definer
set search_path = ''
as $$
declare
  v_recent_count integer;
  v_daily_count integer;
begin
  -- Advisory transaction-level lock per IP to serialize concurrent checks from the same IP
  perform pg_catalog.pg_advisory_xact_lock(pg_catalog.hashtext(p_ip));

  -- 1. Rate limit: max 5 requests per IP in a 3-second window
  select count(*)
  into v_recent_count
  from public.send_logs
  where ip_address = p_ip
    and created_at >= (pg_catalog.now() - interval '3 seconds');

  if v_recent_count >= 5 then
    return false;
  end if;

  -- 2. Daily cap: stop at 400 sends per UTC day
  select count(*)
  into v_daily_count
  from public.send_logs
  where created_at >= pg_catalog.date_trunc('day', pg_catalog.now() at time zone 'utc') at time zone 'utc';

  if v_daily_count >= 400 then
    return false;
  end if;

  -- 3. Atomic log insertion
  insert into public.send_logs (ip_address, receiver, file_name)
  values (p_ip, p_receiver, p_file_name);

  return true;
end;
$$;