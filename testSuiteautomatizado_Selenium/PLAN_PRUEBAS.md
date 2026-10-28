# Plan de pruebas funcionales

Compruebo los seis requisitos en su orden. Ejecuto los casos de interfaz con
Selenium y `unittest` sobre https://farmapulse.onrender.com/comparador.

## 1. RF01: búsqueda y filtrado de medicamentos

- `test_rf01_busqueda_por_nombre`: compruebo los resultados de «Paracetamol».
- `test_rf01_filtrar_por_farmacia`: compruebo el filtro por Mifarma.
- `test_rf01_filtrar_por_farmacias_del_peru`: compruebo el nombre de la
  farmacia en las filas de la tabla, incluidas las que no permiten comprar.

Pendiente: verificar categoría terapéutica y rango de precio. El filtro de
Farmacias del Peru ha devuelto datos de demostración; el caso comprueba la
tabla y no acredita disponibilidad ni precios reales de esa farmacia.

## 2. RF02: comparación de precios

- `test_rf02_precios_ordenados_de_menor_a_mayor`: compruebo al menos dos
  precios unitarios en orden ascendente.

Pendiente: comprobar la equivalencia del producto y la actualidad de los datos.

## 3. RF03: extracción automatizada de precios

Pendiente: comprobar la programación y el resultado de GitHub Actions. La
interfaz no acredita por sí sola que la tarea se haya ejecutado.

## 4. RF04: gestión y persistencia del catálogo

Pendiente: comprobar almacenamiento, actualización y persistencia en
PostgreSQL. La interfaz no acredita por sí sola esos cambios en la base de datos.

## 5. RF05: carrito y entrega

- `test_rf05_agregar_y_retirar_producto`: compruebo que se actualice el carrito.
- `test_rf05_mostrar_despacho_a_domicilio`: compruebo los distritos y la dirección.

Pendiente: comprobar disponibilidad de opciones de entrega por producto.

## 6. RF06: registro e inicio de sesión

- `test_rf06_registro_rechaza_clave_sin_numero`: compruebo el mensaje para una
  contraseña de longitud válida sin números.
- `test_rf06_registro_rechaza_clave_demasiado_corta`: compruebo el mensaje para
  una contraseña que no llega a la longitud mínima.
- `test_rf06_inicio_sesion_con_cuenta_de_prueba`: verifico el acceso con la
  cuenta configurada localmente.

Pendiente: registro exitoso con un correo nuevo y confirmación de la cuenta.

## Registro de resultados

El 28/10/2026 ejecuté seis casos iniciales: 6/6 aprobados. Después ejecuté por
separado la prueba inicial de despacho: 1/1 aprobada. Esos resultados pertenecen
a la versión anterior.

Después de corregir las comprobaciones, ejecuté búsqueda por nombre, filtro
Mifarma, contraseña demasiado corta y orden de precios: **4/4 aprobadas**. En
otra ejecución comprobé el filtro de Farmacias del Peru y el carrito: **2/2
aprobadas**. La prueba de contraseña sin número también pasó en una ejecución
anterior que incluyó otros casos con errores. No he ejecutado todos los casos
juntos después de las modificaciones.
