# Valido el rendimiento de las direcciones

Modifiqué únicamente el límite de `POST /api/direcciones/validar`. Retiré las
diez solicitudes por minuto y eximí esta ruta de los límites generales para
que tampoco herede las cincuenta solicitudes por hora. Conservo los límites
de inicio de sesión, correo, sugerencias de direcciones y pagos.

Reutilizo las conexiones HTTPS a Supabase por hilo. En cada petición envío
sus propias cabeceras y descarto las cookies. No almaceno resultados de
autenticación: sigo verificando revocación, identidad y bloqueo en cada acceso.

## Cómo compruebo la entrada y la salida en Postman

Después del despliegue, envío la petición habitual con una sesión vigente y
reviso las cabeceras de la respuesta:

- `X-Request-ID`: relaciono la petición con sus registros del servidor.
- `X-Request-Started-At`: veo la hora de entrada en UTC (termina en `Z`).
- `X-Request-Finished-At`: veo la hora de salida en UTC.
- `X-Response-Time-Ms`: consulto los milisegundos consumidos dentro de Flask.
- `Server-Timing`: distingo revocación, autenticación, bloqueo y geometría.

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

Guardo los resultados agregados en `validacion-direcciones-100rpm.json`, sin
credenciales ni datos de la cuenta. La ejecución local comprueba el código y
las consultas reales; repito la carga en Render después de integrar y desplegar
el pull request para evaluar también la infraestructura publicada.
