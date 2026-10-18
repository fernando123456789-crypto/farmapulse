# Pagos con Mercado Pago

El checkout muestra directamente los campos seguros de tarjeta y un único botón «Pagar» con el importe. Al abrir el pedido se actualizan las cotizaciones; al pulsar «Pagar» se validan la entrega y la identidad en el servidor antes de tokenizar la tarjeta y crear el cargo. Editar los datos no consume intentos de identidad ni desmonta los campos de tarjeta. El servidor verifica la acreditación, el importe y la referencia y envía el comprobante únicamente después de una aprobación.

Esta versión es una demostración académica con **Checkout API y Secure Fields**, exclusivamente para pruebas. El comprador usa su cuenta de FarmaPulse y una tarjeta oficial de pruebas; no se le solicita una cuenta de Mercado Pago ni un login de billetera. El backend verifica con Mercado Pago que las credenciales pertenezcan a un comercio de pruebas de Perú, tanto al preparar la orden como antes de crearla en el proveedor. Un comercio real o una verificación fallida bloquean el pago, incluso si se llama directamente a la API. No se habilita un modo de cobros reales mediante una variable de entorno.

Para la evaluación puede usarse la Visa de pruebas `4009 1753 3280 6176`, vencimiento `11/30`, CVV `123`, publicados en la [documentación oficial de Mercado Pago](https://www.mercadopago.com.pe/developers/es/docs/checkout-api-orders/integration-test/cards). No se deben ingresar tarjetas reales. La aprobación y el rechazo corresponden al entorno del proveedor; la app no inventa una aprobación local. Las compras nuevas y sus comprobantes se identifican como pruebas, sin cargos ni entregas reales. Una verificación bancaria 3DS es un escenario de prueba distinto de crear una cuenta de Mercado Pago.

Configura las credenciales de tu aplicación en el entorno del servidor:

```dotenv
MERCADO_PAGO_PUBLIC_KEY=
MERCADO_PAGO_ACCESS_TOKEN=
MERCADO_PAGO_WEBHOOK_SECRET=
MERCADO_PAGO_NOTIFICATION_URL=https://tu-dominio/api/pagos/mercadopago/webhook
MAIL_HOST=
MAIL_PORT=587
MAIL_USERNAME=
MAIL_PASSWORD=
MAIL_FROM=
```

Para Gmail, configura `smtp.gmail.com:587` con STARTTLS y una contraseña de aplicación de Google como `MAIL_PASSWORD`. Esta credencial pertenece al remitente y permanece en el servidor. El comprobante se dirige al correo de la sesión autenticada después de acreditarse la orden.

La Public Key puede usarse en el navegador; el Access Token y la clave de firma permanecen en el servidor. Esta versión acepta únicamente credenciales de un comercio de pruebas; no se habilitan cobros reales. Para recibir notificaciones necesitas una URL HTTPS pública, con eventos del tópico `order` habilitados y la clave de firma configurada.

Los pagos pendientes, la verificación bancaria y los fallos de conexión no se muestran como compras exitosas. La protección contra duplicados se aplica tanto en el almacenamiento local como con `X-Idempotency-Key` en la petición a Mercado Pago. Los detalles de configuración, persistencia y conciliación están en [CONFIGURACION.md](CONFIGURACION.md).

Los comprobantes por correo son constancias informativas de pago; no sustituyen una boleta o factura electrónica de SUNAT.

Para probar una aprobación inmediata, activa `MERCADO_PAGO_TEST_APPROVAL=1` y usa una tarjeta oficial de pruebas. El servidor comprueba con `/users/me` que las credenciales pertenezcan a un comercio de pruebas de Perú antes de indicar al SDK el escenario `APRO-AUTH`. El comprobante se identifica como prueba. La identidad del comprador, el importe y la comprobación de acreditación se mantienen; las credenciales de un comercio real no habilitan este escenario. Desactiva esta opción para probar rechazos o el desafío 3DS.
