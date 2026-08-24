-- =============================================================
-- FarmaPulse - Watchlist inicial de medicamentos
-- Pegar en: Supabase Dashboard -> SQL Editor -> New query -> Run
-- =============================================================
-- Estos son los productos que el script nocturno va a buscar
-- cada noche en las 3 farmacias. El campo "nombre" es literalmente
-- el término de búsqueda que se le pasa a buscar_en_farmacias().
-- Puedes editar/agregar filas después desde el Table Editor.

insert into public.medicamentos (nombre, dci, tipo) values
  ('Paracetamol 500mg', 'Paracetamol', 'GENERICO'),
  ('Ibuprofeno 400mg', 'Ibuprofeno', 'GENERICO'),
  ('Amoxicilina 500mg', 'Amoxicilina', 'GENERICO'),
  ('Omeprazol 20mg', 'Omeprazol', 'GENERICO'),
  ('Loratadina 10mg', 'Loratadina', 'GENERICO'),
  ('Metformina 850mg', 'Metformina', 'GENERICO'),
  ('Losartán 50mg', 'Losartán', 'GENERICO'),
  ('Atorvastatina 20mg', 'Atorvastatina', 'GENERICO'),
  ('Azitromicina 500mg', 'Azitromicina', 'GENERICO'),
  ('Diclofenaco 50mg', 'Diclofenaco', 'GENERICO'),
  ('Cetirizina 10mg', 'Cetirizina', 'GENERICO'),
  ('Salbutamol inhalador', 'Salbutamol', 'GENERICO'),
  ('Enalapril 10mg', 'Enalapril', 'GENERICO'),
  ('Ranitidina 150mg', 'Ranitidina', 'GENERICO'),
  ('Ciprofloxacino 500mg', 'Ciprofloxacino', 'GENERICO'),
  ('Naproxeno 500mg', 'Naproxeno', 'GENERICO'),
  ('Clonazepam 2mg', 'Clonazepam', 'GENERICO'),
  ('Metronidazol 500mg', 'Metronidazol', 'GENERICO'),
  ('Levotiroxina 100mcg', 'Levotiroxina', 'GENERICO'),
  ('Amlodipino 5mg', 'Amlodipino', 'GENERICO'),
  ('Panadol', 'Paracetamol', 'MARCA'),
  ('Advil', 'Ibuprofeno', 'MARCA'),
  ('Buscapina', 'Butilhioscina', 'MARCA'),
  ('Doliprane', 'Paracetamol', 'MARCA')
on conflict (nombre, tipo) do nothing;
