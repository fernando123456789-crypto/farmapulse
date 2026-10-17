# Operación segura de FarmaPulse

## Configuración

La API comprueba cada sesión con Supabase y exige un correo confirmado. La API privada solo admite Bearer tokens, sin cookies de autenticación. Las escrituras del navegador requieren JSON y un origen permitido; el webhook se valida con su firma independiente. No se habilita CORS público.

Inicio de sesión admite cinco solicitudes por IP y por cuenta cada quince minutos. Registro, confirmación y recuperación comparten cinco solicitudes por hora, tanto por IP como por correo normalizado. Los contadores usan HMAC para no registrar los correos en sus claves. Supabase conserva sus propios límites, independientes de los de Flask. Los bloqueos de identidad anteriores siguen siendo de cinco fallos. El logout revoca el token en el almacén local incluso cuando Supabase no responde; esta lista se conserva treinta días y se debe compartir entre servidores.

Las sesiones del navegador se guardan por pestaña en `sessionStorage`, sin refresh token persistente. Las sesiones antiguas de `localStorage` se migran al usarlas y se retiran de ese almacenamiento. Cerrar la pestaña requiere iniciar sesión otra vez. Esto reduce la persistencia de credenciales, pero no sustituye las defensas contra XSS.

En producción define `APP_ENV=production`, `APP_BASE_URL=https://tu-dominio` y una `SECRET_KEY` aleatoria de al menos 32 caracteres. Define `RATELIMIT_STORAGE_URI=rediss://...` con Redis privado y TLS, autenticado y persistente. El arranque rechaza producción sin HTTPS configurado o sin Redis. Si hay un proxy, configura explícitamente los hosts permitidos y los proxies de confianza antes de abrir el acceso público: no aceptes cabeceras reenviadas de cualquier origen. Usa un servidor WSGI y un proxy HTTPS; el servidor local de Flask solo sirve para desarrollo.

## Datos y base de datos

Aplica los scripts SQL en orden; `sql/04_endurecimiento_seguridad.sql` contiene la restricción aplicada al proyecto actual. `listas_recetas` solo permite insertar y consultar filas propias con el token del usuario. El backend no usa una clave administrativa para estas operaciones. Los perfiles también se limitan al propietario; las vistas de precios respetan RLS. El catálogo es de lectura pública; la escritura y los registros de scraping son exclusivos del servidor.

La captura nocturna requiere `SUPABASE_SECRET_KEY` o `SUPABASE_SERVICE_ROLE_KEY` privada. En GitHub Actions se utiliza el secreto `SUPABASE_SERVICE_ROLE_KEY`. La clave pública `SUPABASE_KEY` ya no permite escribir el catálogo. El SDK está actualizado para aceptar las nuevas Secret keys de Supabase. Los secretos deben configurarse en cada repositorio; no se copian mediante Git.

Los contextos de compras (correo, DNI, dirección y productos) se cifran con Fernet, autenticados y vinculados a su orden. Al abrir el almacén se migran las filas anteriores sin alterar la compra. La clave de cifrado se deriva de `SECRET_KEY` con separación de propósito. Respalda la base y esa clave en lugares protegidos y separados. No cambies la clave sin un procedimiento de migración: perderla impide recuperar los datos cifrados. Los identificadores de seguridad y tokens revocados solo se guardan como HMAC.

Protege `.env`, `instance/`, los respaldos y los registros con permisos del sistema y cifrado de disco. El cifrado de filas no protege copias históricas anteriores, archivos borrados, correo entregado ni un servidor con su clave comprometida. Define y aplica un plazo de conservación de datos adecuado antes del uso público.

## Pagos y verificaciones

Mercado Pago captura PAN y CVV en sus campos seguros; esos datos no se envían al backend ni se guardan. El servidor valida el propietario de la orden, la firma y vigencia de precios y dirección, el importe, moneda y estado del proveedor. Los cargos y comprobantes conservan controles contra duplicación. Nunca se considera aprobado un pago por una afirmación del navegador.

El webhook requiere la clave de firma y una URL HTTPS pública. Sin esos valores no está operativo; la consulta desde el navegador sigue funcionando mientras la página esté abierta. La aprobación automática de pruebas solo funciona para un comercio verificado como cuenta de pruebas.

Las consultas SQLite emplean parámetros. El frontend escapa contenido y atributos antes de construir HTML. La CSP bloquea scripts inline, objetos, cambios de base y la inclusión en marcos ajenos. Las respuestas de API no se almacenan en caché y las solicitudes tienen un máximo de 128 KiB.

Ejecuta `python -m unittest discover -s tests -p 'test_*.py'` y las pruebas JavaScript de `tests/`. Las pruebas de seguridad comprueban cuotas, CSRF entre orígenes, sesión revocada, entradas malformadas, SQLi, separación entre usuarios y cifrado/migración. `pip-audit -r requirements.txt` revisa vulnerabilidades conocidas de dependencias; Bandit complementa la revisión estática. Los avisos B311 actuales corresponden exclusivamente a la generación de precios de demostración, no a tokens o claves.

En Supabase sigue pendiente habilitar la protección de contraseñas filtradas en la configuración de Auth, si el plan la permite. La conexión disponible permite revisar la base, pero no modificar esa configuración administrada. Consulta los [requisitos de Supabase](https://supabase.com/docs/guides/auth/password-security#password-strength-and-leaked-password-protection). La ausencia de avisos en un escáner no garantiza ausencia de vulnerabilidades; repite la revisión al cambiar permisos, dependencias o despliegue.
