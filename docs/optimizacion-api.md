# Optimización de las rutas API

## Cambios aplicados sin migración de base de datos

| Área | Cambio |
|---|---|
| Proveedores externos | Las conexiones TCP/TLS se reutilizan por hilo en Render. |
| Capacidad I/O | Gunicorn pasa de 4 a 12 hilos, sin aumentar el único worker compatible con el rate limit en memoria. |
| `POST /api/auth/login` | Se elimina una lectura de bloqueo redundante; permanece la comprobación previa al login. |

Las rutas autenticadas conservan la validación actual de firma y expiración del JWT,
sesión activa, token revocado, correo confirmado y bloqueo de identidad. No se añadió
una caché de sesión: cerrar sesión continúa invalidando el token inmediatamente.

También se activó `USE_POOLED_HTTP=1` en Render: por hilo se reutilizan conexiones
TCP/TLS para Supabase Auth, recetas, RENIEC, Photon y Mercado Pago. Gunicorn conserva
un solo worker (compatible con el rate limit en memoria), pero pasa de 4 a 12 hilos;
las operaciones son mayoritariamente espera de red y 20 VUs ya no quedan esperando
solo cuatro huecos de ejecución.

## Mejora opcional pendiente

[`sql/07_sesion_unificada.sql`](../sql/07_sesion_unificada.sql) queda preparado para
una fase posterior. Cuando un administrador de Supabase lo ejecute, podrá habilitarse
la reducción adicional de viajes de sesión a una sola RPC. No es necesario para los
cambios actuales y no debe incluirse en este commit.

## Medición antes/después

No mezclar arranque en frío de Render Free con la prueba. Calienta `/healthz` una vez,
espera a que responda y ejecuta en Postman exactamente el mismo escenario en ambos
despliegues: 20 VUs, 1 minuto, mismos datos y región.

Registrar para cada ruta: p50, p95, p99, máximo, porcentaje de errores y RPS. Los
tiempos de `orden` y `pagar` seguirán incluyendo RENIEC, Mercado Pago y correo: el
cambio elimina cola y viajes redundantes, pero no puede hacer más rápido un proveedor
externo lento. En `/api/direcciones/validar`, los encabezados `Server-Timing` permiten
separar autenticación, seguridad y geometría.
