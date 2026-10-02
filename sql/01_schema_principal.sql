-- =============================================================
-- FarmaPulse - Esquema Principal de Base de Datos (PostgreSQL / Supabase)
-- =============================================================

-- Extensiones requeridas para generación de UUID
create extension if not exists "pgcrypto";

-- 1. Tabla de Farmacias / Cadenas
create table if not exists public.farmacias (
    id serial primary key,
    nombre varchar(100) not null unique,
    url_base varchar(255) not null,
    activo boolean not null default true,
    creado_en timestamptz not null default now()
);

-- 2. Tabla de Distritos
create table if not exists public.distritos (
    id serial primary key,
    nombre varchar(100) not null,
    provincia varchar(100) not null default 'Lima',
    departamento varchar(100) not null default 'Lima',
    unique (nombre, provincia, departamento)
);

-- 3. Tabla Catálogo Maestro de Medicamentos
create table if not exists public.medicamentos (
    id uuid primary key default gen_random_uuid(),
    nombre varchar(255) not null,
    dci varchar(255) not null, -- Denominación Común Internacional (Principio Activo)
    tipo varchar(50) not null check (tipo in ('GENERICO', 'MARCA')),
    laboratorio varchar(150),
    creado_en timestamptz not null default now(),
    constraint uk_medicamento_nombre_tipo unique (nombre, tipo)
);

-- 4. Tabla de Presentaciones Farmacéuticas
create table if not exists public.presentaciones (
    id serial primary key,
    medicamento_id uuid not null references public.medicamentos(id) on delete cascade,
    forma_farmaceutica varchar(100) not null, -- Tableta, Jarabe, Inhalador, etc.
    concentracion varchar(100),              -- 500mg, 10mg/5ml, etc.
    unidades_por_empaque integer default 1
);

-- 5. Tabla Transaccional de Precios Capturados
create table if not exists public.precios (
    id bigserial primary key,
    medicamento_id uuid not null references public.medicamentos(id) on delete cascade,
    farmacia_id integer not null references public.farmacias(id) on delete cascade,
    distrito_id integer references public.distritos(id) on delete set null,
    precio_unitario numeric(10, 4) not null,
    precio_empaque numeric(10, 4),
    moneda varchar(3) default 'PEN',
    en_stock boolean not null default true,
    url_producto text,
    consultado_en timestamptz not null default now()
);

-- Índices B-Tree estratégicos para optimización de reportes y vistas diarias/semanales
create index if not exists idx_precios_consulta_agrupada 
    on public.precios (medicamento_id, farmacia_id, consultado_en);

create index if not exists idx_precios_consultado_en 
    on public.precios (consultado_en);

create index if not exists idx_medicamentos_busqueda 
    on public.medicamentos (nombre, dci);

-- Carga inicial de Cadenas Farmacéuticas soportadas por los scrapers
insert into public.farmacias (nombre, url_base) values
    ('Inkafarma', 'https://inkafarma.pe'),
    ('Mifarma', 'https://mifarma.com.pe'),
    ('Farmacia Universal', 'https://farmaciauniversal.com')
on conflict (nombre) do nothing;

-- Habilitar Row Level Security (RLS) para Supabase
alter table public.farmacias enable row level security;
alter table public.distritos enable row level security;
alter table public.medicamentos enable row level security;
alter table public.presentaciones enable row level security;
alter table public.precios enable row level security;

-- Políticas de lectura pública para clientes
create policy "farmacias_select_public" on public.farmacias for select using (true);
create policy "distritos_select_public" on public.distritos for select using (true);
create policy "medicamentos_select_public" on public.medicamentos for select using (true);
create policy "presentaciones_select_public" on public.presentaciones for select using (true);
create policy "precios_select_public" on public.precios for select using (true);

-- Políticas de inserción para workers y scripts
create policy "precios_insert_service" on public.precios for insert with check (true);