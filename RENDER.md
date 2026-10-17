# Preparo la prueba de pago en Render

El profesor no necesita una cuenta de Mercado Pago ni configurar sus credenciales. Abre la URL HTTPS de FarmaPulse, inicia sesión en FarmaPulse, completa su entrega y usa los campos de tarjeta y Pagar. Las credenciales pertenecen al comercio y se configuran una sola vez en el servidor.

## Configuro el servicio

Conecto Render a la rama `main` del repositorio que contiene esta versión. Para un Web Service Python uso:

```text
Build Command: python -m pip install -r requirements.txt
Start Command: gunicorn --bind 0.0.0.0:$PORT --workers 1 --threads 4 --timeout 60 app:app
```

En el panel del servicio, Environment, configuro los valores privados; Git y los secretos de GitHub Actions no los transfieren automáticamente a Render:

- `SECRET_KEY`: clave aleatoria, estable y privada de al menos 32 caracteres.
- `APP_ENV=production`, `APP_BASE_URL=https://mi-servicio.onrender.com` y `RATELIMIT_STORAGE_URI`: Redis privado compartido, según `SEGURIDAD.md`.
- `SUPABASE_URL` y `SUPABASE_KEY`: proyecto y clave pública de autenticación. Autorizo la URL HTTPS pública de confirmación en Supabase, terminada en `/comparador`.
- `MERCADO_PAGO_PUBLIC_KEY` y `MERCADO_PAGO_ACCESS_TOKEN`: el par de credenciales de la misma aplicación y comercio de pruebas.
- `MERCADO_PAGO_TEST_APPROVAL=1`: solo para la evaluación con un comercio de pruebas. La app verifica esa condición con Mercado Pago; no fuerza aprobaciones en un comercio real.
- `MAIL_HOST`, `MAIL_PORT`, `MAIL_USERNAME`, `MAIL_PASSWORD` y, si necesito un remitente diferente del usuario SMTP, `MAIL_FROM`: correo de comprobantes.
- `RENIEC_TOKEN`: validación de identidad antes del pago.
- `MERCADO_PAGO_WEBHOOK_SECRET` y `MERCADO_PAGO_NOTIFICATION_URL=https://mi-servicio.onrender.com/api/pagos/mercadopago/webhook`: notificaciones firmadas de órdenes, configuradas también en Mercado Pago.

No copio `LOCAL_HTTPS_CERT`, `LOCAL_HTTPS_KEY` ni archivos TLS de mi laptop: Render proporciona HTTPS público. No publico secretos en el repositorio ni los envío al profesor.

Para conservar los pagos, bloqueos y sesiones revocadas de esta implementación, configuro `PAYMENTS_DB` e `IDENTITY_SECURITY_DB` dentro de un disco persistente montado en el servicio, y conservo `SECRET_KEY` e `IDENTITY_SECURITY_KEY`. Por ejemplo, con un disco realmente montado en `/var/data`, uso `/var/data/payments.sqlite3` y `/var/data/identity_security.sqlite3`. Esas rutas por sí solas no crean un disco persistente.

## Compruebo las restricciones del plan

Render Free bloquea conexiones salientes a los puertos SMTP `25`, `465` y `587`; por tanto, el envío actual mediante Gmail SMTP no funcionará allí aunque las credenciales sean correctas. Además, Free no admite discos persistentes y borra los archivos locales al reiniciar o desplegar.

Para evaluar el flujo completo con esta implementación necesito un servicio que permita SMTP y almacenamiento persistente. Si uso Render Free, debo adaptar el correo a un proveedor mediante API HTTPS y sustituir la persistencia local por almacenamiento duradero antes de considerar operativo el flujo completo. Esta adaptación no está incluida en esta guía y no se simula un correo enviado. Consulta las [restricciones oficiales de Render](https://render.com/docs/free#other-limitations) y su [almacenamiento local](https://render.com/docs/free#local-files-lost-on-redeploy).

## Verifico antes de entregar el enlace

Guardo las variables, despliego la versión actual y reviso los registros del servicio. Compruebo que aparezcan los campos seguros de tarjeta, que un pago de pruebas realmente aprobado genere la compra y que el comprobante llegue al correo de la cuenta de FarmaPulse. Uso tarjetas oficiales de pruebas y verifico también un rechazo; no pruebo con tarjetas reales en la evaluación. No basta con cambiar el texto de un error para habilitar la pasarela.

La comprobación de configuración en `/api/config` no muestra claves privadas. Si `pasarela_configurada` es falso, todavía falta la configuración de Mercado Pago o correo en ese servidor; el diagnóstico de variables corresponde al administrador, nunca al cliente. La presencia de variables no demuestra por sí sola que sus credenciales sean válidas ni que SMTP sea accesible.

Sin una URL desplegada y acceso al servicio de Render no puedo verificar la instalación remota. El funcionamiento local y las pruebas automáticas no sustituyen esta comprobación.
