# Optimización de las rutas API

## Cambios aplicados

| Área | Cambio |
|---|---|
| Proveedores externos | Las conexiones TCP/TLS se reutilizan por hilo en Render. |
| Capacidad I/O | Gunicorn pasa de 4 a 12 hilos, sin aumentar el único worker compatible con el rate limit en memoria. |
| `POST /api/auth/login` | Se elimina una lectura de bloqueo redundante; permanece la comprobación previa al login. |
| Sesiones autenticadas | Revocación, usuario y bloqueo pasan de tres viajes remotos a una RPC `fp_session_access`. |
| Búsquedas repetidas | Una sola petición actualiza la caché; los demás hilos esperan el mismo resultado y evitan scraping duplicado. |
| Sugerencias de dirección | Consultas idénticas comparten una sola llamada a Photon, se cachean 60 segundos y reutilizan el último resultado válido ante fallos breves. |

La RPC unificada conserva la validación de firma y expiración del JWT, sesión activa,
token revocado, correo confirmado y bloqueo de identidad. No se añadió una caché de
sesión: cerrar sesión continúa invalidando el token inmediatamente.

También se activó `USE_POOLED_HTTP=1` en Render: por hilo se reutilizan conexiones
TCP/TLS para Supabase Auth, recetas, RENIEC, Photon y Mercado Pago. Gunicorn conserva
un solo worker (compatible con el rate limit en memoria), pero pasa de 4 a 12 hilos;
las operaciones son mayoritariamente espera de red y 20 VUs ya no quedan esperando
solo cuatro huecos de ejecución.

`POST /api/direcciones/sugerencias` conserva sus validaciones y su límite de
peticiones. La llamada a Photon usa tiempos separados de conexión y lectura de 3 y
5 segundos. Una respuesta permanece fresca durante 60 segundos y puede utilizarse
como respaldo durante un máximo de cinco minutos si el proveedor externo falla.
La caché vive solamente en la memoria del proceso y se vacía en cada despliegue.

## Migración aplicada

[`sql/07_sesion_unificada.sql`](../sql/07_sesion_unificada.sql) crea la RPC utilizada
por el código y debe permanecer versionado junto con esta optimización. La migración
se ejecutó en el proyecto Supabase compartido antes de desplegar el código.

## Medición antes/después

No mezclar arranque en frío de Render Free con la prueba. Calienta `/healthz` una vez,
espera a que responda y ejecuta en Postman exactamente el mismo escenario en ambos
despliegues: 20 VUs, 1 minuto, mismos datos y región.

Registrar para cada ruta: p50, p95, p99, máximo, porcentaje de errores y RPS. Los
tiempos de `orden` y `pagar` seguirán incluyendo RENIEC, Mercado Pago y correo: el
cambio elimina cola y viajes redundantes, pero no puede hacer más rápido un proveedor
externo lento. En `/api/direcciones/validar`, los encabezados `Server-Timing` permiten
separar autenticación, seguridad y geometría.
