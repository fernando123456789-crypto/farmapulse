-- Reduce tres viajes HTTP por ruta autenticada (revocación, Auth y bloqueo)
-- a una RPC. Ejecutar después de 06_validacion_direcciones.sql.
-- La función privada ya valida el JWT, la sesión, la revocación y el bloqueo;
-- este envoltorio no concede privilegios adicionales ni acepta identidad del cliente.
create or replace function public.fp_session_access(
  p_token_hash text, p_user_hash text, p_email_hash text
) returns jsonb
language sql stable security invoker set search_path = ''
as $$
  select farmapulse_private.location_access(p_token_hash, p_user_hash, p_email_hash);
$$;

revoke all on function public.fp_session_access(text,text,text) from public, anon;
grant execute on function public.fp_session_access(text,text,text) to authenticated;
