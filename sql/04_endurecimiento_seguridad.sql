-- Aíslo las recetas por propietario y retiro la escritura pública del catálogo.
alter table public.listas_recetas enable row level security;
drop policy if exists listas_recetas_select on public.listas_recetas;
drop policy if exists listas_recetas_insert on public.listas_recetas;
create policy listas_recetas_select on public.listas_recetas for select to authenticated
using ((select auth.uid())::text = usuario_id);
create policy listas_recetas_insert on public.listas_recetas for insert to authenticated
with check ((select auth.uid())::text = usuario_id);
revoke all on public.listas_recetas from anon, authenticated;
grant select, insert on public.listas_recetas to authenticated;
revoke all on public.perfiles from anon, authenticated;
grant select, update on public.perfiles to authenticated;
alter policy perfiles_select_propio on public.perfiles to authenticated using ((select auth.uid()) = id);
alter policy perfiles_update_propio on public.perfiles to authenticated
using ((select auth.uid()) = id) with check ((select auth.uid()) = id);
revoke all on public.precios, public.medicamentos, public.farmacias, public.distritos,
public.presentaciones, public.scrapes_log from anon, authenticated;
grant select on public.precios, public.medicamentos, public.farmacias, public.distritos,
public.presentaciones to anon, authenticated;
drop policy if exists precios_insert on public.precios;
drop policy if exists medicamentos_insert on public.medicamentos;
drop policy if exists farmacias_insert on public.farmacias;
drop policy if exists presentaciones_insert on public.presentaciones;
drop policy if exists scrapes_log_insert on public.scrapes_log;
drop policy if exists scrapes_log_select on public.scrapes_log;
alter view public.variacion_precio_diaria set (security_invoker = true);
alter view public.variacion_precio_semanal set (security_invoker = true);
revoke all on public.variacion_precio_diaria, public.variacion_precio_semanal from anon, authenticated;
grant select on public.variacion_precio_diaria, public.variacion_precio_semanal to anon, authenticated;
alter function public.manejar_nuevo_usuario() set search_path = '';
revoke execute on function public.manejar_nuevo_usuario() from public, anon, authenticated;
