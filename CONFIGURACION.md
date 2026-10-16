# Configuración de integraciones

## Pagos con Mercado Pago

La integración usa [Card Payment Brick de Mercado Pago](https://www.mercadopago.com.pe/developers/es/docs/checkout-bricks/card-payment-brick/default-rendering) para capturar y tokenizar la tarjeta. El backend recibe el token y crea el pago mediante `POST https://api.mercadopago.com/v1/orders`, usando un Access Token privado y `X-Idempotency-Key` con el identificador de la orden interna. El importe se calcula en el servidor a partir de cotizaciones firmadas; se conservan la validación de identidad y la restricción de reparto a los tres distritos permitidos.

Al agregar productos se conserva su cotización firmada en el carrito. Antes de mostrar la tarjeta, `/api/checkout/cotizar` recupera automáticamente los precios de carritos antiguos y cotizaciones vencidas mediante la coincidencia exacta del producto, farmacia y presentación en el catálogo. El precio enviado por el navegador nunca se utiliza para generar la firma. Los nuevos importes aparecen en el resumen y en el formulario antes de confirmar el pago. Las ofertas ambiguas o no disponibles no se sustituyen por otros productos; los resultados de demostración no ofrecen compra. Los productos con cotización vigente evitan una búsqueda adicional.

La compra solo se confirma al recibir `status: processed` y `status_detail: accredited` en la orden y su transacción, importe pagado completo, referencia correcta y moneda PEN. Un pago pendiente no genera comprobante ni vacía el carrito. Si el banco pide autenticación, un iframe de [3DS de Orders](https://www.mercadopago.com.pe/developers/es/docs/checkout-api-orders/payment-management/integrate-3ds) presenta la verificación devuelta por Mercado Pago; el backend vuelve a consultar su estado antes de confirmar. La identidad declarada y el control de la tarjeta son verificaciones distintas: el flujo no certifica que el titular bancario tenga el mismo DNI ingresado en el checkout.

Configura en `.env` las credenciales de tu aplicación de Mercado Pago:

- `MERCADO_PAGO_PUBLIC_KEY`: Public Key utilizada por el SDK en el navegador.
- `MERCADO_PAGO_ACCESS_TOKEN`: Access Token privado, utilizado exclusivamente en el servidor.
- `MERCADO_PAGO_WEBHOOK_SECRET`: clave secreta de firma de Webhooks.
- `MERCADO_PAGO_NOTIFICATION_URL`: URL HTTPS pública terminada en `/api/pagos/mercadopago/webhook`.

Para Gmail, utiliza `smtp.gmail.com`, puerto 587 con STARTTLS y una contraseña de aplicación de Google en `MAIL_PASSWORD`. Se configura una sola vez para el remitente; nunca se solicita acceso al correo del comprador. El destinatario se obtiene de la sesión autenticada, aunque el navegador intente enviar otro email.

También se necesitan `MAIL_HOST`, `MAIL_PORT`, `MAIL_USERNAME`, `MAIL_PASSWORD` y `MAIL_FROM` para los comprobantes. La API Orders utiliza credenciales `APP_USR` de una cuenta de prueba para sandbox; se verificó que la cuenta configurada es de pruebas. Usa credenciales y cuentas de prueba para verificar la integración antes de activar producción. Reinicia el servidor al completar las variables. `.env.example` contiene los nombres sin credenciales; conserva los demás valores de tu `.env` existente.

El webhook valida `x-signature` con HMAC-SHA256 sobre `id:{data.id};request-id:{x-request-id};ts:{ts};`. No confía en el estado del cuerpo recibido: consulta `GET /v1/orders/{id}` con el Access Token, verifica referencia, monto, moneda y tipo de pago, y aplica el resultado a la orden local. Configura eventos del tópico `order` para esta URL en el panel de Mercado Pago; la URL no se envía dentro de la orden. El servidor local no puede recibir notificaciones externas desde `127.0.0.1`; para producción hace falta la URL HTTPS pública y la clave de firma del panel de Mercado Pago. La página abierta consulta el estado del pago cada cuatro segundos durante un período acotado, usando la sesión del comprador.

`instance/payments.sqlite3` (o `PAYMENTS_DB`) conserva los intentos, resultados y datos de compra necesarios para emitir el comprobante cuando llega una notificación posterior. Los tokens y usuarios se indexan mediante HMAC; no se almacena el token de tarjeta, el número de tarjeta ni el CVV. Los datos del pedido, incluyendo nombre, DNI y dirección, permanecen en el almacenamiento del servidor para el comprobante. Conserva el archivo y `SECRET_KEY` en un volumen persistente y respáldalos. Para varios servidores se necesita una base compartida.

La reserva de la orden impide cobros simultáneos duplicados y la transición a aprobado es atómica para no repetir comprobantes. Si se pierde la conexión tras enviar un pago, se informa `sin_confirmar` y no se cobra de nuevo automáticamente: se debe conciliar el resultado con la referencia `fp_...` en Mercado Pago. Un resultado aprobado ya guardado no se reemplaza por notificaciones pendientes atrasadas. Si falla el correo tras aprobarse un pago, la compra conserva su aprobación y se informa que el comprobante quedó pendiente. Una nueva notificación o consulta de ese pago reintenta el envío; también puede ejecutarse `python -m flask --app app reenviar-comprobantes` para los pendientes. Una reserva temporal evita envíos simultáneos. Si Gmail acepta el mensaje y el proceso se interrumpe antes de guardar el resultado, el estado del envío es incierto; SMTP no proporciona una garantía de entrega exactamente una vez. Los comprobantes de órdenes `ORDTST` se marcan como prueba, sin cobro real ni entrega.

Sin credenciales y correo configurados, el checkout no realiza cobros. Las pruebas automáticas simulan respuestas de Mercado Pago; las aprobaciones, rechazos, autenticación bancaria y notificaciones reales requieren validar la aplicación con las credenciales del comercio.

## Intentos de identidad

Se permiten hasta cinco fallos acumulados por cuenta, correo o DNI. Un DNI inexistente o nombres que no coinciden consumen un intento; errores de red, fallos del proveedor y datos incompletos no lo consumen. Una validación correcta no reinicia el contador.

El quinto fallo bloquea permanentemente la cuenta, el correo y el DNI utilizado, incluso con otra cuenta. Los nombres completos se vinculan al DNI; no se bloquean homónimos por su nombre. Se comprueban los bloqueos al registrar cuentas, iniciar sesión, usar sesiones existentes, preparar pagos y cobrar órdenes previamente emitidas. La eliminación de cuenta permanece disponible y no borra los bloqueos.

Los contadores y bloqueos se guardan en SQLite en `instance/identity_security.sqlite3`, fuera del repositorio. Los identificadores se guardan como HMAC, sin correo, DNI o nombres en texto plano. `IDENTITY_SECURITY_DB` permite elegir la ruta y `IDENTITY_SECURITY_KEY` la clave estable (por defecto se usa `SECRET_KEY`). Deben conservarse el archivo y la clave entre reinicios y despliegues; cambiar o borrar cualquiera de ellos pierde la asociación con los bloqueos anteriores. En producción configura un volumen persistente y respalda ambos. Esta implementación admite procesos en el mismo servidor; para varios servidores se necesita un almacén compartido.

## Búsqueda de ubicaciones

Solo se admiten San Borja, San Luis y La Victoria, en Lima. El mapa limita el desplazamiento y el zoom al área de esos distritos, atenúa el exterior y rechaza inmediatamente puntos fuera de los polígonos de cobertura. El servidor aplica la misma restricción independientemente del navegador, del nombre de distrito declarado o de una selección previamente firmada; no permite crear ni cobrar una orden con coordenadas fuera del área permitida.

El checkout combina la búsqueda de calles de [Photon](https://github.com/komoot/photon) con un mapa interactivo [Leaflet](https://leafletjs.com/) y cartografía OpenStreetMap. No requiere clave ni token. La búsqueda se limita a Lima y al distrito seleccionado, descarta zonas generales y evita sugerir un número de puerta distinto al escrito. Cuando no hay un resultado preciso, el usuario conserva su dirección escrita y marca el punto exacto con un clic o arrastrando el marcador; también puede usar el centro del mapa con el teclado.

El servidor verifica el punto contra los polígonos locales de cobertura de San Borja, San Luis y La Victoria, determina el distrito y firma la dirección junto con sus coordenadas. Repite esa comprobación al preparar y cobrar el pago. Las coordenadas se conservan en la orden y se envían como metadatos a Mercado Pago. La cobertura no depende de que Photon conozca el pasaje o número de puerta. Los datos y su procedencia están documentados en `static/data/README.md`; Leaflet 1.9.4 y su licencia se incluyen localmente en `static/vendor/leaflet/`.

La instancia pública `photon.komoot.io` es un servicio comunitario de uso razonable: no ofrece garantía de disponibilidad y puede limitar tráfico alto. Es adecuada para desarrollo y bajo volumen; si aumenta el uso, conviene operar una instancia propia de Photon o usar un proveedor con SLA. Si falla la búsqueda, sigue disponible la elección de coordenadas en el mapa. Los mosaicos se obtienen de `tile.openstreetmap.org`; su atribución se muestra de forma discreta dentro del mapa y debe conservarse.

El mapa comprueba cobertura geográfica. Una calle sugerida no se considera una dirección precisa hasta que se elige el punto de entrega. Ni el punto elegido ni el texto de dirección escrito por el usuario certifican que cada número de puerta exista, que los datos cartográficos estén completos o que una entrega sea posible.
