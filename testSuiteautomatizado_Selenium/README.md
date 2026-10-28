# Pruebas funcionales de FarmaPulse

Uso Selenium con Python y `unittest` para comprobar la aplicación publicada en
https://farmapulse.onrender.com. Los casos están separados de las páginas y sus
identificadores. Cada prueba abre Chrome y lo cierra al terminar, incluso si falla.

Abro esta carpeta en VS Code, elijo el intérprete configurado en `.vscode` y uso
el panel **Pruebas** para descubrir y ejecutar los casos. El caso de inicio de
sesión utiliza las variables locales `SELENIUM_USER_EMAIL` y
`SELENIUM_USER_PASSWORD`, guardadas en `.env.selenium` dentro de esta carpeta.
El archivo está excluido de Git. Si no están disponibles, el caso se omite.

## Relación inicial con los requisitos

- **RF01:** búsqueda por término y filtro por farmacia. Categoría terapéutica,
  rango de precio y la distinción entre nombre comercial y principio activo aún
  requieren comprobación específica; no se consideran cubiertos por estos casos.
- **RF02:** compruebo que los precios visibles estén ordenados. Quedan por
  comprobar la equivalencia del producto entre farmacias y la actualidad de los
  datos; el orden por sí solo no los acredita.
- **RF03:** la ejecución programada de GitHub Actions requiere evidencia del
  flujo y sus ejecuciones; Selenium sobre la interfaz no la acredita.
- **RF04:** la persistencia y actualización en PostgreSQL requieren pruebas y
  evidencia de la base de datos; Selenium sobre la interfaz no las acredita.
- **RF05:** agrego y retiro un producto y compruebo que el checkout muestre
  distritos y dirección de despacho. La disponibilidad de opciones por producto
  todavía requiere una comprobación específica.
- **RF06:** compruebo el rechazo de una clave inválida y el inicio de sesión con
  la cuenta de prueba. El registro exitoso todavía requiere un caso y datos
  adecuados para comprobarlo.

Un resultado verde acredita únicamente las comprobaciones del caso ejecutado.

Para preparar el entorno en Windows, ejecuto `python -m venv .venv` y
`.venv\Scripts\python.exe -m pip install -r requirements.txt`. Copio
`.env.selenium.example` a `.env.selenium` y configuro mi cuenta de prueba
localmente antes de ejecutar los casos que requieren sesión.
