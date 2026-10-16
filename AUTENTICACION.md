# Autenticación

## Eliminación de cuenta

La opción del perfil solicita la contraseña actual y elimina únicamente la cuenta autenticada mediante Supabase Auth Admin API. Para habilitarla, configura en el entorno del servidor una de estas claves administrativas:

```dotenv
SUPABASE_SECRET_KEY=sb_secret_...
```

También se admite el nombre heredado `SUPABASE_SERVICE_ROLE_KEY`. La clave debe permanecer en el servidor, en `.env` local o en el gestor de secretos del despliegue; nunca debe incluirse en JavaScript, HTML ni en Git. La clave pública `SUPABASE_KEY` no autoriza eliminar cuentas.
