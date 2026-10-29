# Informe de interoperabilidad de FarmaPulse

## Objetivo y ejecución

Compruebo la comunicación de FarmaPulse con servicios externos mediante
Selenium y `unittest`. Realizo las solicitudes desde Chrome contra
https://farmapulse.onrender.com. Inicio sesión con la cuenta local de prueba.

Como resultado final comunicado desde la ejecución en VS Code del
**28/10/2026**, registro **15 casos aprobados**. Distingo este resultado informado
de la ejecución inicial registrada automáticamente: en aquella obtuve
13 aprobados y 2 fallos de mapas. El JSON local conserva esa ejecución inicial;
no lo presento como registro de la ejecución posterior. Los resultados describen
estos casos concretos y no representan cobertura total del sistema.

## Servicios, métricas y resultados

### Autenticación con Supabase Auth

Verifico el inicio de sesión real mediante el formulario, que el token pertenezca
al proyecto indicado y que FarmaPulse reconozca al usuario. Compruebo también un
token inválido y el acceso sin token. Los casos **05, 06 y 07 aprobaron**.

Evalúo estado HTTP, estructura de la respuesta e indicador de autenticación.
El caso sin token comprueba un control de acceso; por sí solo no prueba una
llamada a Supabase. Mantengo los tokens fuera de los registros del informe.

### Lectura de PostgreSQL mediante Supabase

Consulto el historial a través de FarmaPulse y verifico `fuente: supabase`, el
formato de lista y la pertenencia de sus registros al usuario autenticado.
Compruebo que una petición anónima sea rechazada. Los casos **08, 09 y 10 aprobaron**.

El caso 09 recibió registros; no di por válida la comprobación con una lista vacía.
El caso 10 comprueba el control de acceso previo a la consulta de datos.
No compruebo escrituras ni demuestro con una única cuenta todos los escenarios
de aislamiento entre usuarios.

Como evidencia complementaria, accedí al proyecto de Supabase indicado y ejecuté
solo una consulta de conteo: observé **237 registros en listas_recetas,
32 861 en precios y 2 664 en scrapes_log**. Estos conteos son una fotografía de
esa consulta; no son cantidades de casos ni de solicitudes procesadas.

### Farmacias y cotización

Consulto Paracetamol en Mifarma y exijo que la fuente de los datos sea
`farmacias`, con productos y precios válidos. Verifico el filtro de farmacia y
que el checkout acepte la cotización real y calcule correctamente los importes.
Los casos **01, 02 y 11 aprobaron**.

Evalúo estado HTTP, campos obligatorios, precios positivos y la igualdad entre
subtotal más entrega y total. No utilizo respuestas demo como prueba de la
conexión real con las farmacias.

### Mapas y servicio Photon

Solicito sugerencias para una avenida pública de San Borja. Espero HTTP 200,
sugerencias con descripción y coordenadas, y coincidencia del distrito.
En la ejecución inicial los casos **12 y 13 fallaron**: FarmaPulse devolvió
**HTTP 502**. En la ejecución posterior comunicada desde VS Code ambos se
informaron como aprobados.

Ambos casos verificaron una misma respuesta reutilizada en la ejecución inicial.
Después los repetí y la aplicación volvió a devolver 502. Una consulta directa
a Photon desde esta laptop respondió HTTP 200 y devolvió 13 sugerencias.
Esa diferencia no identifica por sí sola la causa del fallo inicial desde Render.
Conservo la observación inicial como antecedente. No cambié la aplicación ni
acepté 502 como resultado aprobado.

### Mercado Pago

Compruebo que el navegador cargue el SDK real y que el servidor declare
disponible la configuración de prueba. Los casos **03 y 04 aprobaron**.
Además, durante la preparación consulté el comercio existente con el proveedor
y confirmé su condición de usuario de prueba de Perú.

Estas comprobaciones acreditan carga y disponibilidad, no una transacción.
En esta suite no ejecuté cargos ni validé estados aprobado, rechazado o pendiente.
Esos escenarios requieren casos adicionales de pago de prueba de extremo a extremo.

### DNI y Decolecta

Uso exclusivamente la identidad autorizada en la configuración privada.
Solicito al backend una orden firmada y compruebo que la respuesta incluya el
documento esperado. El caso **14 aprobó**. Conforme al flujo del backend,
la orden se firma después de la validación de identidad con el proveedor.

También compruebo el rechazo de un formato de DNI inválido: el caso **15 aprobó**.
Este último es una validación previa y no acredita una consulta externa.
No probé identidades ajenas ni fallos por nombres incorrectos que consuman
intentos de validación. La orden firmada no ejecuta un pago.

## Tiempos y trazabilidad

Registro el código HTTP y el tiempo observado de cada consulta en milisegundos.
En la primera ejecución observé 2224 ms para la sesión autenticada, 3057 ms
para el historial, 3508 ms para la orden con DNI validado y 2086 ms para la
respuesta 502 de mapas. Son tiempos completos de la API de FarmaPulse, no
tiempos aislados del proveedor.
No definí un umbral de rendimiento porque no se proporcionó un objetivo para
estas integraciones; los tiempos son observaciones, no una prueba de carga.

Reutilizo algunas respuestas entre casos para reducir llamadas. Identifico esa
reutilización en el ejecutor actualizado; los tiempos de la primera ejecución
pueden repetirse entre los casos 01/02, 08/09 y 12/13 por ese motivo.
Un caso no equivale a una nueva solicitud ni a un usuario concurrente.

## Fuentes y alcance

- Proyecto contrastado: https://supabase.com/dashboard/project/gxknyrzcvgddxzfhqyzg
- Data API: https://supabase.com/docs/guides/api
- Selenium WebDriver: https://www.selenium.dev/documentation/webdriver/
- Python unittest: https://docs.python.org/3/library/unittest.html
- Pruebas de Mercado Pago: https://www.mercadopago.com.pe/developers/en/docs/checkout-api-orders/integration-test/cards

Mantengo las credenciales, el documento y los nombres únicamente en el archivo
local excluido de Git. En esta tarea no publiqué cambios ni modifiqué la base de
datos de producción.
