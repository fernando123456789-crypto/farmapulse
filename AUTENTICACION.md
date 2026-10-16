# Autenticación

## Confirmación de correo

El registro y el reenvío de confirmación utilizan Supabase Auth. El SMTP local definido en `MAIL_*` envía comprobantes de compra; no configura automáticamente el SMTP de Supabase. Una respuesta exitosa del proveedor no confirma la entrega en la bandeja del destinatario. Para errores de envío o cuotas la app informa el fallo y conserva la verificación del correo como requisito de acceso.

Configura [Custom SMTP en Supabase](https://supabase.com/docs/guides/auth/auth-smtp), en Authentication → Email → SMTP Settings, usando el remitente autorizado. Para el Gmail configurado en el servidor: host `smtp.gmail.com`, puerto `465` (TLS) o `587` (STARTTLS), usuario y dirección remitente iguales a `MAIL_USERNAME`, contraseña de aplicación igual a `MAIL_PASSWORD` y nombre `ElConerito`. Obtén los valores privados del `.env` local; no los incluyas en Git. Esta configuración se realiza en el proyecto de Supabase, de forma independiente al servidor Flask.

En Authentication → URL Configuration agrega `https://127.0.0.1:5443/comparador` a las redirecciones permitidas para desarrollo. Mantén el dominio público HTTPS al publicar la app. El registro y `/api/auth/reenviar-confirmacion` envían `redirect_to` a Supabase usando `APP_BASE_URL` o el origen HTTPS actual. No se acepta un destino proporcionado por el navegador.

El botón «Reenviar correo de confirmación» permite recuperar una confirmación pendiente desde registro o login sin crear una nueva cuenta. No requiere contraseña ni revela si la dirección corresponde a una cuenta. Se limita a una petición por minuto y tres por hora por IP, además de los límites propios de Supabase.

## Recuperación de contraseña

«Olvidé mi contraseña» solicita un enlace a través de Supabase Auth (`/recover`), con el mismo destino HTTPS autorizado que la confirmación. La respuesta no revela si existe la cuenta. El endpoint mantiene los límites de una solicitud por minuto y tres por hora por IP y no envía enlaces para correos bloqueados por validación de identidad.

El enlace con `type=recovery` abre el formulario de nueva contraseña. La app retira los tokens de la URL, valida la sesión con el servidor y conserva temporalmente la recuperación en `sessionStorage` para permitir recargar la pestaña. La contraseña debe cumplir la política de al menos 12 caracteres, mayúscula, minúscula, número y símbolo. El servidor actualiza únicamente al titular del Bearer token mediante Supabase `/user`; no acepta un identificador ni un correo de destino desde el navegador. Al guardar, se limpia la recuperación y se inicia la sesión. Cancelar descarta los datos temporales; los enlaces vencidos permiten solicitar uno nuevo.

El SMTP de Supabase debe aceptar la autenticación para enviar estos enlaces. El error de Gmail `534 5.7.9 Application-specific password required` indica que la contraseña SMTP guardada debe sustituirse por una contraseña de aplicación válida para el usuario configurado.

## Eliminación de cuenta

La opción del perfil solicita la contraseña actual y elimina únicamente la cuenta autenticada mediante Supabase Auth Admin API. Para habilitarla, configura en el entorno del servidor una de estas claves administrativas:

```dotenv
SUPABASE_SECRET_KEY=sb_secret_...
```

También se admite el nombre heredado `SUPABASE_SERVICE_ROLE_KEY`. La clave debe permanecer en el servidor, en `.env` local o en el gestor de secretos del despliegue; nunca debe incluirse en JavaScript, HTML ni en Git. La clave pública `SUPABASE_KEY` no autoriza eliminar cuentas.
