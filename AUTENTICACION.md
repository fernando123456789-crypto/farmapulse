# Autenticación

## Confirmación de correo

El registro y el reenvío de confirmación utilizan Supabase Auth. El SMTP local definido en `MAIL_*` envía comprobantes de compra; no configura automáticamente el SMTP de Supabase. Una respuesta exitosa del proveedor no confirma la entrega en la bandeja del destinatario. Para errores de envío o cuotas la app informa el fallo y conserva la verificación del correo como requisito de acceso.

Configura [Custom SMTP en Supabase](https://supabase.com/docs/guides/auth/auth-smtp), en Authentication → Email → SMTP Settings, usando el remitente autorizado. Para el Gmail configurado en el servidor: host `smtp.gmail.com`, puerto `587`, usuario y dirección remitente iguales a `MAIL_USERNAME`, contraseña de aplicación igual a `MAIL_PASSWORD` y nombre `FarmaPulse`. Obtén los valores privados del `.env` local; no los incluyas en Git. Esta configuración se realiza en el proyecto de Supabase, de forma independiente al servidor Flask.

En Authentication → URL Configuration agrega `https://127.0.0.1:5443/comparador` a las redirecciones permitidas para desarrollo. Mantén el dominio público HTTPS al publicar la app. El registro y `/api/auth/reenviar-confirmacion` envían `redirect_to` a Supabase usando `APP_BASE_URL` o el origen HTTPS actual. No se acepta un destino proporcionado por el navegador.

El botón «Reenviar correo de confirmación» permite recuperar una confirmación pendiente desde registro o login sin crear una nueva cuenta. No requiere contraseña ni revela si la dirección corresponde a una cuenta. Se limita a una petición por minuto y tres por hora por IP, además de los límites propios de Supabase.

## Eliminación de cuenta

La opción del perfil solicita la contraseña actual y elimina únicamente la cuenta autenticada mediante Supabase Auth Admin API. Para habilitarla, configura en el entorno del servidor una de estas claves administrativas:

```dotenv
SUPABASE_SECRET_KEY=sb_secret_...
```

También se admite el nombre heredado `SUPABASE_SERVICE_ROLE_KEY`. La clave debe permanecer en el servidor, en `.env` local o en el gestor de secretos del despliegue; nunca debe incluirse en JavaScript, HTML ni en Git. La clave pública `SUPABASE_KEY` no autoriza eliminar cuentas.
