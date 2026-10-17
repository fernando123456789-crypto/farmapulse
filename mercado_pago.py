"""Adaptación de órdenes de Mercado Pago sin almacenar datos de tarjeta."""

import re
from decimal import Decimal
from urllib.parse import urlsplit


ORDER_ID = re.compile(r"ORD[A-Z0-9]{20,40}")
PAYMENT_ID = re.compile(r"PAY[A-Z0-9]{20,40}")


def crear_orden(referencia, total, email, cliente, token, metodo, tipo, cuotas):
    importe = f"{total:.2f}"
    return {
        "type": "online", "processing_mode": "automatic",
        "total_amount": importe, "external_reference": referencia,
        "config": {"online": {"transaction_security": {
            "validation": "on_fraud_risk", "liability_shift": "required",
        }}},
        "payer": {"email": email, "first_name": cliente["nombres"], "last_name": cliente["apellidos"],
                  "identification": {"type": "DNI", "number": cliente["dni"]}},
        "transactions": {"payments": [{"amount": importe, "payment_method": {
            "id": metodo, "type": tipo, "token": token, "installments": cuotas,
        }}]},
    }


def leer_orden(datos, referencia, total):
    """Rechaza respuestas ajenas, importes parciales y estados no verificables."""
    pagos = datos["transactions"]["payments"]
    if (not ORDER_ID.fullmatch(str(datos.get("id", ""))) or datos.get("type") != "online"
            or datos.get("external_reference") != referencia or datos.get("currency") != "PEN"
            or Decimal(str(datos["total_amount"])) != total
            or not isinstance(pagos, list) or len(pagos) != 1):
        raise ValueError("Orden no verificable")
    pago = pagos[0]
    metodo = pago["payment_method"]
    if (not PAYMENT_ID.fullmatch(str(pago.get("id", "")))
            or Decimal(str(pago["amount"])) != total
            or metodo.get("type") not in {"credit_card", "debit_card"}):
        raise ValueError("Transacción no verificable")
    estado, detalle = datos.get("status"), datos.get("status_detail")
    resultado = {"orden_proveedor": datos["id"], "pago_id": pago["id"], "status": estado,
                 "status_detail": detalle, "estado": "unknown"}
    if estado == "processed" and detalle == "accredited":
        if (pago.get("status") != "processed" or pago.get("status_detail") != "accredited"
                or Decimal(str(datos.get("total_paid_amount"))) != total
                or Decimal(str(pago.get("paid_amount"))) != total):
            raise ValueError("El importe aún no fue acreditado")
        resultado["estado"] = "approved"
    elif estado in {"created", "processing", "action_required"}:
        resultado["estado"] = "pending"
        seguridad = metodo.get("transaction_security") or {}
        url = seguridad.get("url")
        if detalle == "pending_challenge" and isinstance(url, str):
            parsed = urlsplit(url)
            if (parsed.scheme == "https" and parsed.hostname in {
                    "www.mercadopago.com.pe", "www.mercadopago.com", "www.mercadopago.com.ar",
                } and not parsed.username and not parsed.password and parsed.port in (None, 443)):
                resultado["challenge_url"] = url
    elif estado in {"failed", "canceled", "cancelled", "expired", "refunded", "charged_back"}:
        resultado["estado"] = "rejected"
    return resultado
