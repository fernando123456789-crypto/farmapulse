-- =============================================================
-- FarmaPulse - Log de scraping + vistas de variación de precio
-- Pegar en: Supabase Dashboard -> SQL Editor -> New query -> Run
-- (Requiere que ya hayas corrido el schema principal con
--  medicamentos, farmacias, distritos, presentaciones, precios)
-- =============================================================

-- -------------------------------------------------------------
-- 1) SCRAPES_LOG
-- -------------------------------------------------------------
-- Una fila por cada combinación (farmacia, medicamento, noche).
-- Sin esto, si una farmacia falla una noche no hay forma de
-- distinguir "no había oferta" de "el scraper no pudo conectarse".
create table if not exists public.scrapes_log (
  id uuid primary key default gen_random_uuid(),
  farmacia_id integer not null references public.farmacias (id),
  medicamento_id uuid not null references public.medicamentos (id),
  encontrado boolean not null,
  cantidad_resultados integer not null default 0,
  error text,
  ejecutado_en timestamptz not null default now()
);

create index if not exists idx_scrapes_log_ejecutado_en
  on public.scrapes_log (ejecutado_en);

alter table public.scrapes_log enable row level security;

create policy "scrapes_log_select"
  on public.scrapes_log for select
  using (true);

create policy "scrapes_log_insert"
  on public.scrapes_log for insert
  with check (true);


-- -------------------------------------------------------------
-- 2) VISTA: variación DÍA A DÍA
-- -------------------------------------------------------------
-- Para cada medicamento+farmacia, compara el precio del último
-- scrape contra el del día anterior usando LAG() (window function).
create or replace view public.variacion_precio_diaria as
with precios_por_dia as (
  select
    p.medicamento_id,
    p.farmacia_id,
    p.consultado_en::date as fecha,
    avg(p.precio_unitario) as precio_promedio
  from public.precios p
  group by p.medicamento_id, p.farmacia_id, p.consultado_en::date
),
con_anterior as (
  select
    *,
    lag(precio_promedio) over (
      partition by medicamento_id, farmacia_id
      order by fecha
    ) as precio_dia_anterior
  from precios_por_dia
)
select
  m.nombre as medicamento,
  f.nombre as farmacia,
  c.fecha,
  c.precio_promedio,
  c.precio_dia_anterior,
  round(
    (c.precio_promedio - c.precio_dia_anterior)::numeric, 4
  ) as variacion_soles,
  case
    when c.precio_dia_anterior is null or c.precio_dia_anterior = 0 then null
    else round(
      ((c.precio_promedio - c.precio_dia_anterior) / c.precio_dia_anterior * 100)::numeric, 2
    )
  end as variacion_porcentaje
from con_anterior c
join public.medicamentos m on m.id = c.medicamento_id
join public.farmacias f on f.id = c.farmacia_id
order by c.fecha desc, medicamento, farmacia;


-- -------------------------------------------------------------
-- 3) VISTA: variación SEMANAL
-- -------------------------------------------------------------
-- Mismo principio, pero comparando semana actual contra la anterior.
create or replace view public.variacion_precio_semanal as
with precios_por_semana as (
  select
    p.medicamento_id,
    p.farmacia_id,
    date_trunc('week', p.consultado_en)::date as semana,
    avg(p.precio_unitario) as precio_promedio
  from public.precios p
  group by p.medicamento_id, p.farmacia_id, date_trunc('week', p.consultado_en)::date
),
con_anterior as (
  select
    *,
    lag(precio_promedio) over (
      partition by medicamento_id, farmacia_id
      order by semana
    ) as precio_semana_anterior
  from precios_por_semana
)
select
  m.nombre as medicamento,
  f.nombre as farmacia,
  c.semana,
  c.precio_promedio,
  c.precio_semana_anterior,
  round(
    (c.precio_promedio - c.precio_semana_anterior)::numeric, 4
  ) as variacion_soles,
  case
    when c.precio_semana_anterior is null or c.precio_semana_anterior = 0 then null
    else round(
      ((c.precio_promedio - c.precio_semana_anterior) / c.precio_semana_anterior * 100)::numeric, 2
    )
  end as variacion_porcentaje
from con_anterior c
join public.medicamentos m on m.id = c.medicamento_id
join public.farmacias f on f.id = c.farmacia_id
order by c.semana desc, medicamento, farmacia;
