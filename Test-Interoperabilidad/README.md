# Test de interoperabilidad de FarmaPulse

Uso Selenium y `unittest` para comprobar las respuestas HTTP reales de
[FarmaPulse en Render](https://farmapulse.onrender.com/comparador). Inicio sesión
mediante el formulario y consulto las APIs desde Chrome con la sesión auténtica.
No sustituyo las respuestas de los servicios.

Organizo 15 casos sobre autenticación, lectura de PostgreSQL, farmacias,
cotizaciones, mapas, configuración de Mercado Pago y validación del DNI.
Distingo los casos de integración de los controles de acceso y formato.

## Ejecuto en VS Code

1. Abro esta carpeta y habilito su confianza si VS Code la solicita.
2. Selecciono `.venv/Scripts/python.exe` como intérprete de Python.
3. Configuro mi cuenta y la identidad autorizada en `.env.interoperabilidad`.
   Uso `.env.interoperabilidad.example` como guía; el archivo real permanece local.
   Reemplazo `PONER_DNI_AQUI`, `PONER_NOMBRES_AQUI` y `PONER_APELLIDOS_AQUI`
   antes de comprobar la identidad. Si los dejo como ejemplo, esos casos se omiten.
4. Abro el matraz **Pruebas** y ejecuto un caso o toda la suite.

Para preparar otra computadora, ejecuto `python -m venv .venv` y
`.venv\Scripts\python.exe -m pip install -r requirements.txt`.

## Genero el informe de ejecución

Ejecuto `.venv\Scripts\python.exe ejecutar.py`. Registro los estados, tiempos y
códigos HTTP en `resultados/ultima_ejecucion.json`, sin guardar respuestas,
credenciales o identidades personales. El resultado del ejecutor muestra los
fallos reales; no los convierto en aprobados ni reintento cargos.

Reutilizo algunas respuestas dentro de una ejecución para reducir llamadas y
respetar los límites de los proveedores. Las identifico en las mediciones; un
caso no equivale necesariamente a una solicitud nueva.

En [INFORME.md](INFORME.md) explico el resultado obtenido, la evidencia de
Supabase y el alcance de cada integración. Los estados de pagos aprobados,
rechazados y pendientes y la escritura en PostgreSQL requieren casos adicionales.
