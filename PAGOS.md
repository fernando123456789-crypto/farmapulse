# Configuración de pagos

El checkout usa Culqi para aceptar pagos con tarjeta y Yape. Las claves de prueba y producción se configuran en el entorno del servidor; nunca se publican en el navegador ni en el repositorio.

Configura estas variables en `.env` para desarrollo o en el gestor de secretos del servicio de despliegue:

```dotenv
CULQI_PUBLIC_KEY=pk_test_...
CULQI_SECRET_KEY=sk_test_...
MAIL_HOST=smtp.example.com
MAIL_PORT=587
MAIL_USERNAME=cuenta@example.com
MAIL_PASSWORD=contraseña-de-aplicación
MAIL_FROM=FarmaPulse <cuenta@example.com>
```

Mantén las claves de prueba durante la validación. Antes de recibir pagos reales, reemplázalas por las claves live del panel de Culqi y configura un servicio SMTP con autorización para enviar desde `MAIL_FROM`. No compartas `CULQI_SECRET_KEY` ni la contraseña SMTP.

El servidor calcula el monto a partir de cotizaciones firmadas y recientes, crea una orden Culqi para el checkout multipago y solo confirma la compra cuando Culqi devuelve un cargo exitoso con el importe y moneda esperados. Los comprobantes enviados por correo son constancias informativas de pago; no sustituyen una boleta o factura electrónica emitida conforme a SUNAT.
