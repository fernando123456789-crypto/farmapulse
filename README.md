# FarmaPulse

Aplicación web para comparar medicamentos, preparar un carrito y evaluar un
checkout académico con Mercado Pago. El backend usa Python y Flask; la interfaz
usa HTML y JavaScript.

## Pasarela vigente

La integración actual utiliza **Mercado Pago Checkout API (Orders) y Secure
Fields**, exclusivamente en modo de pruebas. Los campos de tarjeta pertenecen al
proveedor y el servidor recibe un token. El comprador inicia sesión en FarmaPulse;
el flujo no le solicita una cuenta de Mercado Pago.

Los detalles de la pasarela, las credenciales y los comprobantes están en
[PAGOS.md](PAGOS.md).

## DNI e identidad del comprador

Al pulsar **Pagar**, el servidor valida los datos de entrega y consulta el DNI
mediante Decolecta. Comprueba un DNI de ocho dígitos y compara los nombres y
apellidos normalizados antes de autorizar la tokenización y el pago. Escribir o
editar los campos no consume por sí solo intentos de validación.

`RENIEC_TOKEN` se configura únicamente en el servidor. Los detalles del proveedor,
las respuestas de error y los intentos permitidos están en
[CONFIGURACION.md](CONFIGURACION.md).

La coincidencia del DNI con los nombres declarados no certifica la titularidad
bancaria de la tarjeta; la autorización bancaria corresponde al proveedor de pago.

## Flujo de compra de prueba

1. Iniciar sesión y agregar productos con cotizaciones firmadas al carrito.
2. Completar los datos del comprador y elegir el punto de entrega en San Borja,
   San Luis o La Victoria.
3. Pulsar Pagar: el backend valida entrega, identidad, cotización e importe.
4. El SDK tokeniza la tarjeta de prueba y el backend solicita la orden a Mercado Pago.
5. La compra solo se confirma después de verificar acreditación, importe, moneda
   y referencia. Un resultado pendiente no se presenta como una aprobación.

## Archivos principales

- `mercado_pago.py`: construcción y verificación de órdenes del proveedor.
- `static/js/mercado-pago.js`: integración de los campos seguros de tarjeta.
- `app.py`: rutas del checkout y consulta de DNI.
- `identity_security.py`: contadores y bloqueos de identidad.
- `tests/test_card_payments.py`: escenarios del pago con tarjeta.
- `tests/test_identity_security.py`: validaciones e intentos de identidad.

## Instalación y configuración

Consultar [INSTALACION.md](INSTALACION.md), [RENDER.md](RENDER.md) y
[AUTENTICACION.md](AUTENTICACION.md). `.env.example` enumera las variables de
configuración; los secretos reales permanecen fuera del repositorio.
