# Pagos con Mercado Pago

El checkout acepta tarjetas mediante Card Payment Brick de Mercado Pago. El servidor crea y consulta pagos con la API oficial, verifica el importe y la referencia de la compra y envía el comprobante únicamente después de una aprobación.

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

La Public Key puede usarse en el navegador; el Access Token y la clave de firma permanecen en el servidor. Usa las credenciales y usuarios de pruebas de Mercado Pago antes de habilitar cobros reales. Para recibir notificaciones necesitas una URL HTTPS pública, con eventos del tópico `order` habilitados y la clave de firma configurada.

Los pagos pendientes, la verificación bancaria y los fallos de conexión no se muestran como compras exitosas. La protección contra duplicados se aplica tanto en el almacenamiento local como con `X-Idempotency-Key` en la petición a Mercado Pago. Los detalles de configuración, persistencia y conciliación están en [CONFIGURACION.md](CONFIGURACION.md).

Los comprobantes por correo son constancias informativas de pago; no sustituyen una boleta o factura electrónica de SUNAT.
