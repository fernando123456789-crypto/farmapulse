-- Compruebo el acceso en una sola consulta con el JWT verificado por PostgREST.
-- No cambio tablas, datos ni políticas existentes.
create schema if not exists farmapulse_private;
revoke all on schema farmapulse_private from public, anon;
grant usage on schema farmapulse_private to authenticated;

create or replace function farmapulse_private.location_access(
  p_token_hash text, p_user_hash text, p_email_hash text
) returns jsonb
language plpgsql stable security definer set search_path = ''
as $$
declare
  caller uuid := auth.uid();
  claims jsonb := auth.jwt();
  account record;
  session_id uuid;
  is_blocked boolean;
begin
  if caller is null or claims->>'role' is distinct from 'authenticated' then
    return jsonb_build_object('estado', 'invalida');
  end if;
  if p_token_hash is null or p_user_hash is null or p_email_hash is null
     or p_token_hash !~ '^[a-f0-9]{64}$' or p_user_hash !~ '^[a-f0-9]{64}$'
     or p_email_hash !~ '^[a-f0-9]{64}$' then
    raise invalid_parameter_value using message = 'Invalid security fingerprints';
  end if;
  select u.id, u.email, u.email_confirmed_at, u.is_anonymous into account
  from auth.users u where u.id = caller
    and u.email_confirmed_at is not null and not coalesce(u.is_anonymous, false)
    and (u.banned_until is null or u.banned_until <= now());
  if not found then
    return jsonb_build_object('estado', 'invalida');
  end if;
  begin
    session_id := (claims->>'session_id')::uuid;
  exception when invalid_text_representation then
    return jsonb_build_object('estado', 'invalida');
  end;
  if session_id is null or not exists (
    select 1 from auth.sessions s where s.id = session_id and s.user_id = caller
      and (s.not_after is null or s.not_after > now())
  ) then
    return jsonb_build_object('estado', 'invalida');
  end if;
  if exists (select 1 from public.fp_revoked_tokens t
             where t.token_hash = p_token_hash and t.expires_at > now()) then
    return jsonb_build_object('estado', 'revocada');
  end if;
  select exists (select 1 from public.fp_identity_attempts a
                 where a.identifier in (p_user_hash, p_email_hash) and a.blocked)
  into is_blocked;
  return jsonb_build_object(
    'estado', case when is_blocked then 'bloqueada' else 'valida' end,
    'usuario', jsonb_build_object('id', account.id, 'email', account.email,
      'email_confirmed_at', account.email_confirmed_at, 'is_anonymous', account.is_anonymous)
  );
end;
$$;
revoke all on function farmapulse_private.location_access(text,text,text) from public, anon;
grant execute on function farmapulse_private.location_access(text,text,text) to authenticated;

-- Expongo únicamente una envoltura sin privilegios propios. La función con
-- privilegios queda en un esquema privado y deriva el usuario del JWT firmado.
create or replace function public.fp_location_access(
  p_token_hash text, p_user_hash text, p_email_hash text
) returns jsonb
language sql stable security invoker set search_path = ''
as $$
  select farmapulse_private.location_access(p_token_hash, p_user_hash, p_email_hash);
$$;
revoke all on function public.fp_location_access(text,text,text) from public, anon;
grant execute on function public.fp_location_access(text,text,text) to authenticated;
