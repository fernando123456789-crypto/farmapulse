# Resiliencia y control de tráfico de la API

## Contexto detectado

- **Runtime:** Python 3.12.
- **Framework:** Flask 3.1.
- **Arquitectura:** aplicación web Flask modular; API REST, persistencia local/SQLite en desarrollo o Supabase en producción, y consumo de Supabase Auth, RENIEC, Photon, Mercado Pago y Resend.
- **Dependencias:** `requests`, `Flask-Limiter` y `redis` ya están en `requirements.txt`; no se agregó ninguna dependencia.
- **Alcance:** las llamadas salientes hechas por el cliente compartido de `http_client.py`, `_external_request` en `app.py` y el transporte HTTP de Resend. Los scrapers de farmacias y el transporte SMTP tienen clientes propios, por lo que esta política no los intercepta.

## Diseño aplicado

La política está aislada en `resilience.py` y la invocan `ThreadLocalHTTP`, `_external_request` y el transporte HTTPS de Resend, sin guardar credenciales ni cookies. En desarrollo, `_external_request` conserva el transporte `requests` existente para no romper la configuración ni los dobles de prueba; en producción, `USE_POOLED_HTTP=1` utiliza las sesiones por hilo ya configuradas. SMTP y los scrapers de farmacias conservan sus transportes propios y quedan fuera de esta política.

### Retry

- Máximo **3 intentos en total** (la llamada inicial y hasta 2 reintentos).
- Backoff exponencial con jitter completo: `uniform(0, min(2 s, 0.25 s × 2^n))`.
- Solo se reintentan timeouts, errores de conexión y respuestas HTTP `408`, `425`, `429`, `500`, `502`, `503` o `504`.
- `Retry-After` se interpreta para segundos o fecha HTTP y se limita al máximo de espera configurado.
- Los métodos `GET`, `HEAD` y `OPTIONS` se pueden reintentar. Otros métodos solo se reintentan si incluyen una cabecera `Idempotency-Key` o `X-Idempotency-Key`. Así, el pago de Mercado Pago puede reintentarse con su clave de orden, mientras que registro, login y otros `POST` sin clave no duplican operaciones.
- Errores de validación del cliente (`4xx`, excepto los estados transitorios indicados) se devuelven sin reintentos.

### Circuit breaker

- Un circuito independiente por host, con estados **Closed**, **Open** y **Half-Open**.
- Se abre tras **5 fallos transitorios consecutivos** (timeouts, errores de conexión, `408` o `5xx`).
- Permanece abierto durante **30 segundos**; después permite una sola petición de prueba. Un resultado exitoso lo cierra y un nuevo fallo vuelve a abrirlo.
- Las llamadas bloqueadas no contactan al proveedor. Flask devuelve `503`, un mensaje genérico, `Retry-After` y `X-Resilience-Circuit: open`. El log registra únicamente el host y la transición, nunca URL completa, credenciales ni datos de usuario.
- El estado vive en memoria del proceso; no se comparte entre procesos ni instancias. En el despliegue actual de Render hay un worker. Para múltiples workers/instancias haría falta compartir el estado del circuito.

### Rate limiter

Flask-Limiter ya está aplicado en la aplicación, por IP y con límites particulares por endpoint (por ejemplo, `POST /api/direcciones/sugerencias`: **20 por minuto**; login: **5 por 15 minutos** por IP y cuenta). Al superar el límite se responde **429 Too Many Requests** antes de ejecutar el servicio. `RATELIMIT_STORAGE_URI` permite usar Redis compartido; en producción la configuración ya exige Redis o una aceptación explícita de almacenamiento en memoria con un solo worker.

## Ejecución y casos de prueba

Ejecuta las pruebas deterministas de reintentos y circuito:

```powershell
python -m unittest discover -s tests -p "test_http_resilience.py" -v
```

Los casos comprueban backoff y jitter, no reintentar validaciones ni operaciones POST sin idempotencia, reintentar operaciones con `Idempotency-Key`, apertura y recuperación del circuito y exclusión de pruebas Half-Open concurrentes. El límite `429` de sugerencias ya se comprueba en `tests/test_location_performance.py` y los límites de autenticación en `tests/test_security_hardening.py`.

## Pruebas manuales y evidencias

1. **Respuesta 429.** Con una cuenta de prueba autenticada, envía 21 solicitudes válidas en menos de un minuto al endpoint de sugerencias. Ejemplo en PowerShell (la solicitud no incluye `Origin`, por lo que sirve también fuera del navegador):

   ```powershell
   1..21 | ForEach-Object {
     curl.exe -s -o NUL -w "%{http_code}`n" `
       -X POST "$env:BASE_URL/api/direcciones/sugerencias" `
       -H "Authorization: Bearer $env:ACCESS_TOKEN" `
       -H "Content-Type: application/json" `
       --data-binary '{"texto":"Avenida de prueba"}'
   }
   ```

   Captura los códigos `200`/respuesta de negocio de las solicitudes permitidas y el `429` al agotar el límite; el token se obtiene de un entorno de prueba y no se guarda en el reporte.

2. **Retry y circuit breaker.** Los proveedores externos no deben recibir pruebas de fallo inducidas desde producción. Usa las pruebas unitarias anteriores para verificar el umbral y captura la salida del runner. En una caída real observa cambios como:

   ```text
   INFO resilience circuit_breaker servicio=photon.komoot.io estado=half_open
   WARNING resilience circuit_breaker servicio=photon.komoot.io estado=open
   ```

   Una petición bloqueada devuelve `503`, `Retry-After` y `X-Resilience-Circuit: open`. No registres ni captures cabeceras `Authorization`, tokens o datos personales.

3. **Reporte de mantenimiento.** Registra fecha, versión desplegada, endpoint, proveedor afectado, transición de circuito, cantidad de `429`/`503` y resultado de la recuperación. Compara tasas y latencias p95 antes y después con el mismo conjunto de solicitudes; no uses datos reales de pagos ni credenciales productivas.

## Mantenimiento y configuración

Los valores se mantienen como parámetros predeterminados en `ResiliencePolicy` (máximo de intentos, backoff, umbral y espera del circuito); se pueden ajustar allí junto con sus pruebas. Los cambios de configuración del rate limiter se realizan con `RATELIMIT_STORAGE_URI` y los límites declarados en `app.py`. No se deben aumentar reintentos de operaciones con efectos secundarios sin una clave de idempotencia admitida por el proveedor.
