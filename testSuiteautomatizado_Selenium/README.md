# Test Suite automatizado con Selenium

Desarrollé esta suite para comprobar las funciones de
[FarmaPulse en Render](https://farmapulse.onrender.com/comparador) mediante
Selenium, Python y `unittest`. Organicé los identificadores y las acciones de
cada página por separado de los casos de prueba.

## Casos que ejecuto

1. **RF01 — Búsqueda y filtrado:** compruebo la búsqueda de Paracetamol y los
   filtros por Mifarma y Farmacias del Peru.
2. **RF02 — Comparación de precios:** verifico el orden ascendente de los
   precios unitarios mostrados.
3. **RF03 — Captura automatizada:** identifico como pendiente la verificación
   de la ejecución programada en GitHub Actions.
4. **RF04 — Persistencia del catálogo:** identifico como pendiente la
   comprobación de los datos en PostgreSQL.
5. **RF05 — Carrito y entrega:** agrego y retiro un producto; también
   compruebo los distritos y la dirección de despacho.
6. **RF06 — Registro e inicio de sesión:** verifico el rechazo de contraseñas
   inválidas y el acceso con una cuenta de prueba.

La suite contiene **nueve casos de interfaz**. Mantengo RF03 y RF04 como
pendientes porque necesitan evidencia adicional de los procesos internos.
En el filtro de Farmacias del Peru he observado datos de demostración; la
prueba comprueba la tabla sin acreditar disponibilidad ni precios reales.

## Cómo ejecuto las pruebas

1. Abro esta carpeta en VS Code y selecciono un intérprete de Python con
   Selenium instalado. Para crear el entorno en Windows, ejecuto:

   ```powershell
   python -m venv .venv
   .\.venv\Scripts\python.exe -m pip install -r requirements.txt
   ```

2. Configuro `SELENIUM_USER_EMAIL` y `SELENIUM_USER_PASSWORD` en el archivo
   local `.env.selenium`. Mantengo este archivo fuera de Git. En una copia del
   repositorio puedo crear el archivo a partir de `.env.selenium.example`.
3. Abro el panel **Pruebas** y ejecuto el caso deseado o toda la suite. Si no
   configuro la cuenta, los casos que la necesitan se marcan como omitidos.

En [PLAN_PRUEBAS.md](PLAN_PRUEBAS.md) relaciono los casos con cada requisito y
detallo su alcance. Compruebo cada resultado en la ejecución correspondiente.
