# Valido el rendimiento de las direcciones

Modifiqué únicamente el límite de `POST /api/direcciones/validar`. Retiré las
diez solicitudes por minuto y eximí esta ruta de los límites generales para
que tampoco herede las cincuenta solicitudes por hora. Conservo los límites
de inicio de sesión, correo, sugerencias de direcciones y pagos.

Reutilizo las conexiones HTTPS a Supabase por hilo. En cada petición envío
sus propias cabeceras y descarto las cookies. No almaceno resultados de
autenticación: sigo verificando revocación, identidad y bloqueo en cada acceso.
En producción reúno las comprobaciones en una sola consulta. PostgREST verifica
la firma y la caducidad del JWT; la función comprueba la cuenta confirmada,
la sesión vigente, las revocaciones y los bloqueos con los datos actuales.

Mantengo la función con privilegios en un esquema privado y expongo una
envoltura sin privilegios propios, accesible solo con una sesión autenticada.
Derivo el usuario del JWT validado. Las referencias que leo localmente del token
solo sirven para calcular huellas; no autorizo usando contenido sin verificar.
Comparo la identidad devuelta por la base con esas referencias antes de aceptar
el resultado. No cambio datos ni políticas existentes.

## Cómo compruebo la entrada y la salida en Postman

Después del despliegue, envío la petición habitual con una sesión vigente y
reviso las cabeceras de la respuesta:

- `X-Request-ID`: relaciono la petición con sus registros del servidor.
- `X-Request-Started-At`: veo la hora de entrada en UTC (termina en `Z`).
- `X-Request-Finished-At`: veo la hora de salida en UTC.
- `X-Response-Time-Ms`: consulto los milisegundos consumidos dentro de Flask.
- `Server-Timing`: distingo `seguridad`, `geometria` y `total`. En desarrollo
  con SQLite también distingo revocación, autenticación y bloqueo por separado.

También registro la entrada y la salida en el servidor con el identificador
de la petición. No registro tokens, nombres, correos, coordenadas ni direcciones.

En **Scripts → Post-response** puedo usar:

```javascript
const entrada = pm.response.headers.get("X-Request-Started-At");
const salida = pm.response.headers.get("X-Request-Finished-At");
const tiempo = pm.response.headers.get("X-Response-Time-Ms");
pm.test("Recibo mediciones de entrada y salida", () => {
  pm.expect(entrada).to.be.a("string");
  pm.expect(salida).to.be.a("string");
  pm.expect(tiempo).to.not.equal(null);
  pm.expect(Number(tiempo)).to.be.at.least(0);
});
console.log({
  id: pm.response.headers.get("X-Request-ID"),
  entrada, salida, servidor_ms: Number(tiempo),
  postman_ms: pm.response.responseTime,
  etapas: pm.response.headers.get("Server-Timing"),
});
```

Comparo el tiempo del servidor con el de Postman. El tiempo de Postman incluye
red, conexión y esperas anteriores a Flask; esa diferencia no identifica por
sí sola una cola de Render. El detalle de las etapas permite comprobar dónde
espera el servidor cuando responde.

## Alcance de mi comprobación de carga

Ejecuto la ruta local con Supabase real y hasta cuatro hilos, enviando cien
solicitudes a una frecuencia de cien por minuto. Reutilizo una cuenta de prueba;
no presento esa ejecución como cien identidades distintas ni como una prueba
de cien usuarios simultáneos.

Guardo los resultados en `validacion-direcciones-100rpm.json`, sin credenciales
ni datos de la cuenta. En la versión inicial obtuve una máxima de 2283 ms y en
una segunda comprobación tres respuestas superaron el segundo. Después de
reunir las comprobaciones en una consulta obtuve cien HTTP 200 por debajo de
1000 ms: media de 138,528 ms, percentil 95 de 199,592 ms y máxima de 431,322 ms.
La primera consulta, medida aparte sin calentar esa conexión, tardó 672,130 ms.

Verifico también la función en Supabase: firma alterada y llamada anónima
devuelven 401. Pruebo sesión válida, revocación, bloqueo y sesión inexistente
en una transacción con datos sintéticos que revierto por completo. No conservo
cambios de esas pruebas en las tablas.

La ejecución local comprueba el código y las consultas reales. Esta muestra
no garantiza un máximo permanente: repito la carga en Render después de
integrar y desplegar el pull request para evaluar la infraestructura publicada.
La función SQL nueva ya está instalada en Supabase y no la usa la aplicación
anterior. Conservo su definición en `sql/06_validacion_direcciones.sql`.
