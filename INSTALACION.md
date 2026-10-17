# Ejecuto FarmaPulse en otra laptop Windows

Cada instalación necesita su propia configuración privada. Git incluye el código completo y `.env.example`; no incluye `.env`, las bases locales, sesiones ni certificados. Los secretos de GitHub Actions tampoco se descargan al clonar el repositorio.

1. Actualizo el código desde la carpeta del repositorio:

   ```powershell
   git pull --ff-only origin main
   ```

2. Instalo Python 3.12 y Git para Windows, y después las dependencias del proyecto:

   ```powershell
   python -m pip install -r requirements.txt
   ```

3. Creo `.env` a partir de `.env.example` **solo si todavía no existe**. Configuro una `SECRET_KEY` nueva y privada para esta instalación; las claves públicas de Supabase permiten iniciar sesión. Para que aparezcan los campos de tarjeta, la app también necesita la Public Key y el Access Token de Mercado Pago, además del correo de comprobantes (`MAIL_HOST`, `MAIL_USERNAME`, `MAIL_PASSWORD` y un remitente válido). El remitente usa `MAIL_FROM` o, por defecto, `MAIL_USERNAME`. `RENIEC_TOKEN` permite validar el DNI al confirmar el pago. Uso credenciales de pruebas para las pruebas.

   Genero una clave local sin reutilizar la de otro servidor:

   ```powershell
   python -c "import secrets; print(secrets.token_urlsafe(48))"
   ```

   Guardo ese resultado únicamente en mi `.env`. No publico ese archivo ni envío credenciales por el repositorio. Solo configuro claves administrativas si esta instalación está autorizada para las funciones de administración; no son necesarias para mostrar los campos de tarjeta.

4. Genero y autorizo el certificado local en **esta laptop**, sin copiar la clave privada de otro equipo:

   ```powershell
   .\scripts\configurar_https_local.ps1
   ```

5. Compruebo los requisitos sin mostrar ningún secreto:

   ```powershell
   python scripts/diagnosticar_instalacion.py
   ```

6. Inicio la app y abro su dirección HTTPS en la misma laptop:

   ```powershell
   python app.py
   ```

   [Abrir instalación local](https://127.0.0.1:5443/comparador).

Si falla el script por la política de PowerShell o la instalación del certificado, reviso el error concreto; no desactivo las protecciones de Windows ni la validación HTTPS del navegador. En Supabase debo tener autorizada la URL de confirmación `https://127.0.0.1:5443/comparador` para iniciar sesión desde el enlace de correo.

Si el diagnóstico no encuentra faltantes y los campos siguen sin aparecer, reviso el mensaje exacto del checkout. Un bloqueador de contenido, un certificado no confiable, la falta de conexión con Mercado Pago o una versión antigua del código pueden impedir cargar el SDK. El diagnóstico comprueba presencia de configuración, no la validez de las credenciales con los proveedores.

`127.0.0.1` siempre se refiere al equipo donde se abre el navegador. La dirección local del desarrollador no abre su servidor desde otra laptop. Para compartir una misma instalación sin distribuir secretos se necesita desplegarla en un servidor con dominio HTTPS; no es suficiente compartir un enlace a localhost.
