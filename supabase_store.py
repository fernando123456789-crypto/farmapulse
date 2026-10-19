"""Registro de pagos, bloqueos de identidad y sesiones revocadas en Supabase (Postgres).

Sustituye a los SQLite locales, que Render Free borra en cada despliegue. Se usa la clave
secreta de Supabase (SUPABASE_SECRET_KEY, rol ``service_role``) SOLO desde el servidor:
las tablas tienen RLS activado y sin políticas, así que el navegador (clave pública) no
puede leerlas ni escribirlas. Ver sql/05_pagos_y_seguridad.sql.

Ambas clases exponen la misma interfaz que ``PaymentLedger`` e ``IdentitySecurity``
(SQLite), así que app.py y el panel /admin no cambian su lógica.
"""

import hashlib
import hmac
import json
import time
from datetime import datetime, timezone

import requests

from payment_ledger import LedgerBase

T_PAGOS = "fp_payments"
T_INTENTOS = "fp_identity_attempts"
T_REVOCADOS = "fp_revoked_tokens"
_PAGINA_ADMIN = 1000  # filas por solicitud al leer el panel (límite por defecto de PostgREST)


class StoreError(RuntimeError):
    """El almacenamiento en Supabase no respondió o rechazó la operación."""


class SupabaseRest:
    """Cliente mínimo de PostgREST con la clave de servicio. Nunca se envía al navegador."""

    def __init__(self, url, service_key, session=None, timeout=10):
        url = (url or "").strip().rstrip("/")
        service_key = (service_key or "").strip()
        if not url.startswith("https://") or not service_key:
            raise ValueError("Configura SUPABASE_URL (https) y SUPABASE_SECRET_KEY para usar Supabase")
        self.base = f"{url}/rest/v1"
        self.timeout = timeout
        self.session = session or requests.Session()
        self.headers = {"apikey": service_key, "Content-Type": "application/json"}
        # Las claves antiguas (service_role) son JWT y también van en Authorization.
        # Las nuevas (sb_secret_...) no son JWT: solo se envían en `apikey`.
        if service_key.startswith("eyJ"):
            self.headers["Authorization"] = f"Bearer {service_key}"

    def request(self, method, path, *, params=None, body=None, prefer=None, retries=0):
        headers = dict(self.headers)
        if prefer:
            headers["Prefer"] = prefer
        for intento in range(retries + 1):
            try:
                respuesta = self.session.request(
                    method, f"{self.base}/{path}", params=params,
                    data=None if body is None else json.dumps(body), headers=headers, timeout=self.timeout,
                )
            except requests.RequestException as error:
                if intento < retries:
                    time.sleep(0.3)
                    continue
                raise StoreError("No se pudo contactar a Supabase") from error
            if respuesta.status_code >= 500 and intento < retries:
                time.sleep(0.3)
                continue
            if respuesta.status_code >= 400:
                # El cuerpo del error no se registra: puede incluir nombres de columnas o datos.
                raise StoreError(f"Supabase respondió {respuesta.status_code} en {path.split('?')[0]}")
            if not respuesta.content:
                return None
            try:
                return respuesta.json()
            except ValueError as error:
                raise StoreError("Respuesta inválida de Supabase") from error
        raise StoreError("No se pudo contactar a Supabase")  # pragma: no cover

    def rpc(self, funcion, argumentos):
        return self.request("POST", f"rpc/{funcion}", body=argumentos)


def _iso_utc(valor):
    """'YYYY-MM-DD HH:MM:SS' (UTC, formato del panel) -> ISO 8601 con 'Z' para PostgREST."""
    return valor.replace(" ", "T") + "Z"


def _texto_panel(valor):
    """timestamptz ISO de Postgres -> 'YYYY-MM-DD HH:MM:SS' en UTC, el formato que lee admin_panel."""
    if not valor:
        return None
    try:
        momento = datetime.fromisoformat(str(valor).replace("Z", "+00:00"))
    except ValueError:
        return None
    if momento.tzinfo is None:
        momento = momento.replace(tzinfo=timezone.utc)
    return momento.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


class SupabasePaymentLedger(LedgerBase):
    def __init__(self, rest, secret):
        super().__init__(secret)
        self.rest = rest

    def claim(self, order_id, token, device, owner):
        r = self.rest.rpc("fp_payment_claim", {
            "p_order_id": order_id, "p_token_hash": self._hash(token),
            "p_device_hash": self._hash(device), "p_owner_hash": self._hash(owner),
        })
        tipo = r.get("kind") if isinstance(r, dict) else None
        if tipo == "new":
            return None
        if tipo == "response":
            return r["response"], r["status"]
        if tipo == "processing":
            return {"ok": False, "estado": "procesando",
                    "error": "Este pago ya se está procesando. No generes otro cobro"}, 409
        if tipo == "pending":
            return {"ok": False, "estado": "sin_confirmar", "referencia": r.get("referencia"),
                    "error": "Ya hay un pago pendiente de confirmación. Contacta a soporte antes de pagar otra vez"}, 409
        if tipo == "conflict":
            return {"ok": False, "estado": "conflicto",
                    "error": "La orden o el token ya se utilizaron en otro intento de pago"}, 409
        raise StoreError("Respuesta inesperada al reservar la orden")

    def finish(self, order_id, state, response, status):
        # Nunca degrada una orden ya aprobada (misma regla que en SQLite).
        params = [("order_id", f"eq.{order_id}")]
        if state != "approved":
            params.append(("state", "neq.approved"))
        self.rest.request("PATCH", T_PAGOS, params=params,
                          body={"state": state, "response": response, "status": status})

    def set_context(self, order_id, context):
        self.rest.request("PATCH", T_PAGOS, params=[("order_id", f"eq.{order_id}"), ("context", "is.null")],
                          body={"context": self._encrypt_context(order_id, context)})

    def get(self, order_id, owner=None):
        filas = self.rest.request("GET", T_PAGOS, retries=1, params={
            "select": "state,response,status,context,owner_hash", "order_id": f"eq.{order_id}", "limit": 1})
        if not filas:
            return None
        fila = filas[0]
        if owner is not None and not hmac.compare_digest(fila["owner_hash"], self._hash(owner)):
            return None
        return {"state": fila["state"], "response": fila["response"], "status": fila["status"],
                "context": self._decrypt_context(order_id, fila["context"]) if fila["context"] else None}

    def settle(self, order_id, state, response, status):
        r = self.rest.rpc("fp_payment_settle", {
            "p_order_id": order_id, "p_state": state, "p_response": response, "p_status": status})
        return r["response"], r["status"], bool(r["newly_approved"])

    def claim_receipt(self, order_id):
        return self.rest.rpc("fp_payment_claim_receipt", {"p_order_id": order_id}) is True

    def release_receipt(self, order_id):
        self.rest.request("PATCH", T_PAGOS, params={"order_id": f"eq.{order_id}"}, body={"receipt_lease": None})

    def admin_list(self, desde_utc=None, hasta_utc=None):
        """Órdenes para /admin leídas de Supabase (sin DNI ni dirección). Pagina de 1000 en 1000."""
        filtros = []
        if desde_utc:
            filtros.append(("created_at", f"gte.{_iso_utc(desde_utc)}"))
        if hasta_utc:
            filtros.append(("created_at", f"lt.{_iso_utc(hasta_utc)}"))
        resultado, desplazamiento = [], 0
        while True:
            filas = self.rest.request("GET", T_PAGOS, retries=1, params=[
                ("select", "order_id,state,context,created_at"), *filtros,
                ("order", "created_at.desc,order_id.desc"),
                ("limit", _PAGINA_ADMIN), ("offset", desplazamiento)]) or []
            resultado.extend(self._fila_admin(f["order_id"], f["state"], f["context"], _texto_panel(f["created_at"]))
                             for f in filas)
            if len(filas) < _PAGINA_ADMIN:
                return resultado
            desplazamiento += _PAGINA_ADMIN

    def pending_receipts(self):
        filas = self.rest.request("GET", T_PAGOS, retries=1, params={
            "select": "order_id,response", "state": "eq.approved"}) or []
        return [f["order_id"] for f in filas if not (f["response"] or {}).get("comprobante_enviado")]


class SupabaseIdentitySecurity:
    MAX_FAILURES = 5

    def __init__(self, rest, secret):
        self.rest = rest
        self.secret = secret.encode("utf-8")

    def _keys(self, identifiers):
        return sorted({
            hmac.new(self.secret, f"{kind}:{value}".encode("utf-8"), hashlib.sha256).hexdigest()
            for kind, value in identifiers.items() if value
        })

    def revoke_token(self, token):
        key = self._keys({"sesion": token})[0]
        self.rest.rpc("fp_revoke_token", {"p_token_hash": key, "p_ttl_seconds": 30 * 86400})

    def token_revoked(self, token):
        key = self._keys({"sesion": token})[0]
        ahora = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        filas = self.rest.request("GET", T_REVOCADOS, retries=1, params={
            "select": "token_hash", "token_hash": f"eq.{key}", "expires_at": f"gt.{ahora}", "limit": 1})
        return bool(filas)

    def status(self, identifiers):
        keys = self._keys(identifiers)
        if not keys:
            return {"blocked": False, "remaining": self.MAX_FAILURES}
        lista = ",".join(f'"{k}"' for k in keys)
        filas = self.rest.request("GET", T_INTENTOS, retries=1, params={
            "select": "failures,blocked", "identifier": f"in.({lista})"}) or []
        failures = max((f["failures"] for f in filas), default=0)
        blocked = any(f["blocked"] for f in filas)
        return {"blocked": bool(blocked), "remaining": max(0, self.MAX_FAILURES - failures)}

    def record_failure(self, identifiers):
        r = self.rest.rpc("fp_identity_record_failure",
                          {"p_keys": self._keys(identifiers), "p_max": self.MAX_FAILURES})
        return {"blocked": bool(r["blocked"]), "remaining": int(r["remaining"])}
