# Despliego FarmaPulse en Render (plan Free)

El profesor no necesita una cuenta de Mercado Pago ni configurar sus credenciales. Abre la URL HTTPS de FarmaPulse, inicia sesión, completa su entrega y usa los campos de tarjeta y Pagar. Las credenciales pertenecen al comercio y se configuran una sola vez en el servidor.

## Qué cambia en Render Free y cómo lo resuelvo

| Limitación de Render Free | Solución en esta versión |
|---|---|
| El disco local se borra en cada despliegue | Pagos, bloqueos de identidad y sesiones revocadas viven en Supabase (`sql/05_pagos_y_seguridad.sql`) |
| Bloquea SMTP (puertos 25, 465 y 587) | `EMAIL_PROVIDER=resend`: el comprobante sale por la API HTTPS de Resend |
| No incluye Redis | `RATELIMIT_ALLOW_MEMORY=1` con un solo worker (o una instancia de Render Key Value) |
| Memoria limitada | `requirements.txt` no incluye Playwright ni navegadores; solo los usa el scraper de GitHub Actions |

## 1. Preparo Supabase

1. Supabase → SQL Editor → pego y ejecuto `sql/05_pagos_y_seguridad.sql` (se puede repetir sin problema). Crea `fp_payments`, `fp_identity_attempts` y `fp_revoked_tokens` con RLS activado y sin políticas: el navegador (clave pública) no puede leerlas ni escribirlas.
2. Supabase → Project Settings → API Keys → copio la clave **secret** (`sb_secret_...`, o `service_role` en proyectos antiguos). Solo va en Render → Environment como `SUPABASE_SECRET_KEY`. Nunca en el navegador, en Git ni en el chat.

## 2. Configuro el servicio

Conecto Render a la rama `main`. Para un Web Service Python:

```text
Build Command: python -m pip install -r requirements.txt
Start Command: gunicorn --bind 0.0.0.0:$PORT --workers 1 --threads 4 --timeout 60 app:app
Health Check Path: /healthz
```

El archivo `.python-version` fija Python 3.12 (si no, Render usa el predeterminado según la fecha de creación del servicio). Dejo **un solo worker**: el límite de peticiones en memoria solo es correcto con un proceso.

## 3. Variables en Render → Environment

Render define solo `RENDER`, `RENDER_EXTERNAL_URL` y `RENDER_EXTERNAL_HOSTNAME`; la app las usa como URL pública si no pones `APP_BASE_URL`.

| Variable | Valor |
|---|---|
| `APP_ENV` | `production` |
| `SECRET_KEY` | aleatoria, privada, estable, de 32+ caracteres (cambiarla vuelve ilegibles los pagos cifrados) |
| `APP_BASE_URL` | `https://TU-SERVICIO.onrender.com` (opcional en Render; obligatoria con dominio propio) |
| `STORAGE_BACKEND` | `supabase` |
| `SUPABASE_URL`, `SUPABASE_KEY` | URL del proyecto y clave pública (publishable/anon) |
| `SUPABASE_SECRET_KEY` | clave secreta de Supabase (solo servidor) |
| `RATELIMIT_ALLOW_MEMORY` | `1` (o `RATELIMIT_STORAGE_URI=redis://...` con Render Key Value) |
| `MERCADO_PAGO_PUBLIC_KEY`, `MERCADO_PAGO_ACCESS_TOKEN` | credenciales de PRUEBA del mismo comercio de pruebas de Perú |
| `MERCADO_PAGO_TEST_APPROVAL` | `1` (solo con comercio de pruebas) |
| `MERCADO_PAGO_WEBHOOK_SECRET`, `MERCADO_PAGO_NOTIFICATION_URL` | opcionales; URL `https://TU-SERVICIO.onrender.com/api/pagos/mercadopago/webhook` |
| `EMAIL_PROVIDER` | `resend` |
| `RESEND_API_KEY`, `RESEND_FROM` | clave de Resend y remitente, p. ej. `FarmaPulse <onboarding@resend.dev>` |
| `RENIEC_TOKEN` | token de Decolecta |
| `ADMIN_EMAIL` | correo del administrador (la contraseña vive solo en Supabase Auth) |

Con `onboarding@resend.dev`, Resend solo entrega al correo de tu propia cuenta de Resend: para probar, inicia sesión en FarmaPulse con ese mismo correo. Para enviar a cualquiera, verifica un dominio en Resend y usa un remitente de ese dominio.

No copio `LOCAL_HTTPS_CERT`, `LOCAL_HTTPS_KEY`, `MAIL_*` (solo SMTP local), `PAYMENTS_DB` ni `IDENTITY_SECURITY_DB` (solo SQLite local).

Git y los secretos de GitHub Actions no se transfieren a Render: cada variable se carga en su panel. Las claves del scraper (`SUPABASE_URL`, `SUPABASE_SERVICE_ROLE_KEY`) siguen en GitHub → Settings → Secrets and variables → Actions.

## 4. Configuro el panel de administración (`/admin`)

1. **Crear la cuenta.** Supabase → Authentication → Users → *Add user*: correo del administrador, contraseña nueva y *Auto Confirm User*.
2. **Declarar el rol.** `ADMIN_EMAIL=<correo>` en Render → Environment. Sin esta variable nadie es administrador y `/api/admin/*` responde 403.
3. **Uso.** Inicio sesión en la página principal; aparece «Administración» en el menú. Abro `/admin` desde ese enlace, en la misma pestaña (la sesión vive en `sessionStorage`).

El panel lee `fp_payments` en Supabase, así que las compras sobreviven a los despliegues. Reglas de cálculo: solo `approved` suma compras e ingresos; `pending`, `processing`, `unknown` y `rejected` se listan sin sumar; cada orden es una fila única; el ingreso es el total cobrado (productos + delivery); las fechas se muestran en hora de Lima (UTC-5). El panel no muestra DNI ni dirección.

## 5. Verifico antes de entregar el enlace

1. `https://TU-SERVICIO.onrender.com/healthz` responde `{"ok": true}`.
2. `https://TU-SERVICIO.onrender.com/api/config` muestra `"pasarela_configurada": true`. Si es `false`: falta una clave de Mercado Pago, falta el correo (`RESEND_API_KEY` y `RESEND_FROM`) o las credenciales no son de un comercio de pruebas de Perú.
3. Pago de prueba con una tarjeta oficial de pruebas: queda aprobado y se muestra el comprobante.
4. Supabase → Table Editor → `fp_payments`: aparece la fila con `state = approved` (el campo `context` está cifrado: es lo esperado).
5. Llega el correo al buzón de la sesión (revisa también spam). Si falla, el pago sigue aprobado y el comprobante queda pendiente: se reintenta con una consulta del estado o con `python -m flask --app app reenviar-comprobantes`.
6. `/admin` con la cuenta administradora muestra la compra y el ingreso.

Render Free duerme el servicio tras 15 minutos sin tráfico: la primera petición tarda unos segundos en despertar.
