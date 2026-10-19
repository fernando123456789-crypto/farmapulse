"""Envío de correos transaccionales: Resend (API HTTPS) en producción, SMTP en local.

Render Free bloquea los puertos SMTP (25, 465 y 587), así que en Render el proveedor debe
ser ``resend``, que usa HTTPS (puerto 443). El SMTP de Gmail se conserva como opción local.

Variables: EMAIL_PROVIDER (``resend`` | ``smtp``), RESEND_API_KEY, RESEND_FROM y, para SMTP,
MAIL_HOST, MAIL_PORT, MAIL_USERNAME, MAIL_PASSWORD, MAIL_FROM. Si EMAIL_PROVIDER está vacío,
se usa Resend cuando hay RESEND_API_KEY y SMTP en caso contrario.
"""

import smtplib
import ssl
from email.message import EmailMessage

import requests

RESEND_URL = "https://api.resend.com/emails"


class MailError(Exception):
    """No se pudo enviar el correo (el mensaje nunca incluye claves ni datos personales)."""


def proveedor(config):
    elegido = (config.get("provider") or "").strip().lower()
    if elegido in {"resend", "smtp"}:
        return elegido
    return "resend" if (config.get("resend_api_key") or "").strip() else "smtp"


def correo_configurado(config):
    if proveedor(config) == "resend":
        return bool((config.get("resend_api_key") or "").strip() and (config.get("resend_from") or "").strip())
    return bool(config.get("host") and config.get("username") and config.get("password") and config.get("from"))


def enviar_correo(config, destino, asunto, texto, idempotency_key=None):
    """Envía un correo de texto plano. Lanza MailError si falla."""
    if not correo_configurado(config):
        raise MailError("El correo no está configurado")
    if proveedor(config) == "resend":
        _enviar_resend(config, destino, asunto, texto, idempotency_key)
    else:
        _enviar_smtp(config, destino, asunto, texto)


def _enviar_resend(config, destino, asunto, texto, idempotency_key):
    cabeceras = {
        "Authorization": f"Bearer {config['resend_api_key'].strip()}",
        "Content-Type": "application/json",
        "User-Agent": "farmapulse/1.0",
    }
    if idempotency_key:
        # Evita un segundo correo si se reintenta el mismo comprobante (Resend lo recuerda 24 h).
        cabeceras["Idempotency-Key"] = idempotency_key[:256]
    try:
        respuesta = requests.post(RESEND_URL, headers=cabeceras, timeout=15, json={
            "from": config["resend_from"].strip(), "to": [destino], "subject": asunto, "text": texto})
    except requests.RequestException as error:
        raise MailError("No se pudo contactar a Resend") from error
    if respuesta.status_code >= 400:
        detalle = ""
        try:
            cuerpo = respuesta.json()
            detalle = str(cuerpo.get("message") or cuerpo.get("name") or "")[:200]
        except (ValueError, AttributeError):
            pass
        raise MailError(f"Resend rechazó el envío ({respuesta.status_code}) {detalle}".strip())


def _enviar_smtp(config, destino, asunto, texto):
    mensaje = EmailMessage()
    mensaje["Subject"] = asunto
    mensaje["From"] = config["from"]
    mensaje["To"] = destino
    mensaje.set_content(texto)
    try:
        with smtplib.SMTP(config["host"], int(config.get("port") or 587), timeout=15) as servidor:
            servidor.starttls(context=ssl.create_default_context())
            servidor.login(config["username"], config["password"])
            servidor.send_message(mensaje)
    except (smtplib.SMTPException, OSError) as error:
        raise MailError("No se pudo enviar por SMTP") from error
