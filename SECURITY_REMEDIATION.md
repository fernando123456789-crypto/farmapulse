# Mitigación de alertas ZAP — seguridad-login

## Alcance y estado

Trabajo basado en dos capturas con 13 tipos de alerta, sin las URL, parámetros,
evidencias ni versión del escáner. Las pruebas locales verifican controles del
código; no equivalen a un nuevo escaneo del despliegue ni permiten cerrar todas
las instancias originales. No se suprimen reglas de ZAP para obtener cero alertas.

## Tratamiento de las 13 alertas

1. **Content Security Policy Header Not Set.** Política de respuesta central en
   `http_security.py`, aplicada también a API, estáticos y errores. Scripts,
   estilos y fuentes locales; sin `unsafe-inline` ni `unsafe-eval`. Los datos
   geográficos se pasan como JSON en un atributo HTML, sin JavaScript inline.
2. **Missing Anti-clickjacking Header.** `frame-ancestors 'none'` y
   `X-Frame-Options: DENY`. La aplicación no podrá incrustarse en un iframe.
3. **Sub Resource Integrity Attribute Missing.** Cada script y hoja de estilo
   incluida en las páginas lleva SHA-384 y `crossorigin`. El build genera
   `static/asset-integrity.json`; las pruebas comparan hashes con archivos reales.
4. **Cross-Domain JavaScript Source File Inclusion.** Se elimina el runtime CDN
   de Tailwind. Tailwind se compila; Font Awesome y Poppins se sirven localmente,
   con versiones fijadas en `package-lock.json` y licencias conservadas.
5. **Strict-Transport-Security Header Not Set.** HSTS en HTTPS; HTTPS obligatorio
   fuera de desarrollo. No se activa `includeSubDomains` ni preload sin verificar
   todos los subdominios. Ver configuración del proxy más abajo.
6. **Timestamp Disclosure - Unix.** Las respuestas de Auth se limitan a `id` y
   `email`, sin timestamps/metadatos completos del proveedor. Se conservan fechas
   funcionales de consultas y recetas. No se alteran JWT ni fechas HTTP para
   ocultar detecciones. **Pendiente identificar la evidencia original:** un número
   de diez dígitos puede ser un falso positivo; no se declara cerrada esta alerta.
7. **X-Content-Type-Options Header Missing.** `nosniff` en todas las respuestas.
8. **Authentication Request Identified.** Informativa: detectar un login es
   esperado. Se prueba CSRF, cookies Secure/HttpOnly/SameSite, errores genéricos
   y limitación de intentos. Puede seguir apareciendo correctamente en ZAP.
9. **Sensitive Information in URL.** Formularios con método POST explícito incluso
   sin JS; búsqueda solo por POST JSON; la API rechaza queries sin reflejarlas.
   El pedido ya no se incluye en el enlace de WhatsApp: el usuario copia la lista,
   abre el chat y la pega. El botón general usa un saludo público, sin datos del
   usuario. Rechazar una query no borra el registro del servidor/proxy de una URL
   ya enviada: configurar redacción de logs y revisar la evidencia original.
10. **Suspicious Comments.** Comentarios de plantillas convertidos a comentarios
    Jinja, ausentes del HTML servido. Los comentarios de JS revisados describen
    funcionamiento, sin credenciales. **Pendiente comparar el comentario exacto
    del informe**; no se declara eliminada una evidencia desconocida.
11. **Modern Web Application.** Informativa: describe una interfaz con JavaScript.
    No se elimina funcionalidad para ocultar esta detección. Reescanear con AJAX
    spider y una sesión autenticada para cubrir flujos dinámicos.
12. **Re-examine Cache-control Directives.** HTML con CSRF, API y errores usan
    `no-store`. Archivos estáticos públicos requieren revalidación para evitar
    servir JS antiguo con un hash SRI nuevo. El proxy/CDN debe respetar la política.
13. **User Agent Fuzzer.** Informativa: comprobar diferencias entre agentes.
    Las pruebas verifican que variar User-Agent no elude la autenticación.
    Comparar respuestas concretas del informe antes de cerrar su revisión.

## Instalación y desarrollo

Python 3.12 y Node.js con npm. Se añadió `python-dotenv`, que faltaba pese a
importarse al iniciar. Se eliminó la dependencia de Talisman del código y se
unificó la política para evitar cabeceras contradictorias.

```sh
python -m venv .venv
# Activar .venv según el sistema operativo
pip install -r requirements.txt
npm ci --ignore-scripts
npm run build
```

Los recursos compilados están versionados. Repetir el build al cambiar cualquier
JS/CSS o clases Tailwind en las plantillas, y reiniciar Flask para cargar el
manifiesto actualizado. No modificar assets mediante un CDN después del build.

Definir `SECRET_KEY` con un valor aleatorio privado, `FLASK_ENV=development`
únicamente para HTTP local, y ejecutar `flask --app app run`. No subir `.env`.
El comparador y pruebas pueden arrancar sin Supabase; para login real hacen falta
`SUPABASE_URL` y `SUPABASE_KEY`. El cliente Python `supabase` sigue siendo opcional
en esta aplicación y es necesario para persistir recetas en su base de datos.

## Despliegue

- No definir `FLASK_ENV=development` en producción. Utilizar un servidor WSGI
  detrás de TLS; no exponer el servidor de desarrollo de Flask.
- `TRUSTED_PROXY_HOPS` vale 0 por defecto. Configurarlo con el número exacto de
  proxies confiables que sobrescriben `X-Forwarded-For` y `X-Forwarded-Proto`.
  El backend no debe ser accesible directamente desde Internet si confía en esas
  cabeceras. Una configuración incorrecta puede causar bucles HTTPS o permitir
  suplantación de IP/esquema. No asumir un valor sin conocer el alojamiento.
- Si nginx/CDN sirve estáticos o errores sin pasar por Flask, configurar allí
  también las cabeceras y comprobar las respuestas finales externas.
- Mantener HSTS solo cuando HTTPS esté operativo. La política tiene un año de
  duración y no incluye subdominios.
- Flask-Limiter conserva el almacenamiento en memoria existente: para múltiples
  workers/instancias configurar almacenamiento compartido mediante
  `RATELIMIT_STORAGE_URI` en la configuración de Flask (y el driver correspondiente).
- El frontend conserva el modelo Bearer existente en localStorage. La CSP es una
  defensa adicional, no una garantía frente a todo XSS ni una auditoría completa
  de almacenamiento de sesiones, RLS de Supabase o dependencias.

## Verificación

```sh
python -m unittest discover -s tests -v
node --check static/js/auth.js
node --check static/js/main.js
node --check static/js/whatsapp.js
git diff --check
```

Las pruebas simulan las respuestas de Supabase; no crean cuentas ni consultan
farmacias. Cubren páginas/errores/estáticos, HTTPS/cookies, CSRF, login/registro,
logout, límites, búsqueda/recetas, User-Agent, integridad y exposición de datos.

Después de desplegar, repetir ZAP sobre la URL y rama correctas, sin credenciales
en URL, con sesión autenticada y AJAX spider. Guardar el informe con evidencias
por URL para determinar qué alertas se cerraron y cuáles son informativas o falsos
positivos. No se ejecutó una auditoría remota activa desde este trabajo.

## Referencias

- https://cheatsheetseries.owasp.org/cheatsheets/HTTP_Headers_Cheat_Sheet.html
- https://flask-wtf.readthedocs.io/en/1.2.x/csrf/
- https://developer.mozilla.org/en-US/docs/Web/Security/Defenses/Subresource_Integrity
- https://v3.tailwindcss.com/docs/installation
- https://www.zaproxy.org/docs/desktop/addons/passive-scan-rules/
