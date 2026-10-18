"""Control persistente de envíos de cargos para evitar cobros duplicados."""

import hashlib
import base64
import hmac
import json
import sqlite3
import time
from contextlib import closing
from pathlib import Path
from cryptography.fernet import Fernet


class PaymentLedger:
    def __init__(self, path, secret):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.secret = secret.encode()
        self.cipher = Fernet(base64.urlsafe_b64encode(hmac.new(
            self.secret, b"farmapulse-payment-context-v1", hashlib.sha256,
        ).digest()))
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute("""CREATE TABLE IF NOT EXISTS payments (
                order_id TEXT PRIMARY KEY, token_hash TEXT NOT NULL UNIQUE,
                device_hash TEXT NOT NULL, state TEXT NOT NULL,
                response TEXT, status INTEGER, owner_hash TEXT, context TEXT, created_at TEXT
            )""")
            if "owner_hash" not in {row[1] for row in db.execute("PRAGMA table_info(payments)")}:
                db.execute("ALTER TABLE payments ADD COLUMN owner_hash TEXT")
            if "context" not in {row[1] for row in db.execute("PRAGMA table_info(payments)")}:
                db.execute("ALTER TABLE payments ADD COLUMN context TEXT")
            if "created_at" not in {row[1] for row in db.execute("PRAGMA table_info(payments)")}:
                db.execute("ALTER TABLE payments ADD COLUMN created_at TEXT")
            if "receipt_lease" not in {row[1] for row in db.execute("PRAGMA table_info(payments)")}:
                db.execute("ALTER TABLE payments ADD COLUMN receipt_lease REAL")
            # Conservo las compras anteriores y cifro sus datos personales al abrir la base.
            db.execute("PRAGMA secure_delete = ON")
            for order_id, context in db.execute("SELECT order_id, context FROM payments WHERE context IS NOT NULL").fetchall():
                if not context.startswith("fernet:"):
                    db.execute("UPDATE payments SET context = ? WHERE order_id = ?",
                               (self._encrypt_context(order_id, json.loads(context)), order_id))

    def _encrypt_context(self, order_id, context):
        envelope = json.dumps({"order_id": order_id, "data": context}).encode()
        return "fernet:" + self.cipher.encrypt(envelope).decode()

    def _decrypt_context(self, order_id, value):
        envelope = json.loads(self.cipher.decrypt(value.removeprefix("fernet:").encode()))
        if envelope["order_id"] != order_id:
            raise ValueError("El contexto no corresponde a la orden")
        return envelope["data"]

    def _hash(self, value):
        return hmac.new(self.secret, value.encode(), hashlib.sha256).hexdigest()

    def claim(self, order_id, token, device, owner):
        token_hash, device_hash = self._hash(token), self._hash(device)
        with closing(sqlite3.connect(self.path, timeout=10)) as db, db:
            db.execute("BEGIN IMMEDIATE")
            existing = db.execute(
                "SELECT order_id, token_hash, device_hash, state, response, status, owner_hash FROM payments "
                "WHERE order_id = ? OR token_hash = ?", (order_id, token_hash),
            ).fetchall()
            if existing:
                if (len(existing) != 1 or existing[0][:3] != (order_id, token_hash, device_hash)
                        or existing[0][6] != self._hash(owner)):
                    return {"ok": False, "estado": "conflicto", "error": "La orden o el token ya se utilizaron en otro intento de pago"}, 409
                _, _, _, state, response, status, _ = existing[0]
                if response:
                    return json.loads(response), status
                return {"ok": False, "estado": "procesando", "error": "Este pago ya se está procesando. No generes otro cobro"}, 409
            pending = db.execute("SELECT order_id FROM payments WHERE owner_hash = ? AND state IN ('processing', 'unknown', 'pending')",
                                 (self._hash(owner),)).fetchone()
            if pending:
                return {"ok": False, "estado": "sin_confirmar", "referencia": pending[0],
                        "error": "Ya hay un pago pendiente de confirmación. Contacta a soporte antes de pagar otra vez"}, 409
            db.execute("INSERT INTO payments (order_id, token_hash, device_hash, owner_hash, state, created_at) VALUES (?, ?, ?, ?, 'processing', CURRENT_TIMESTAMP)",
                       (order_id, token_hash, device_hash, self._hash(owner)))
            return None

    def finish(self, order_id, state, response, status):
        with closing(sqlite3.connect(self.path, timeout=10)) as db, db:
            db.execute("UPDATE payments SET state = ?, response = ?, status = ? WHERE order_id = ? "
                       "AND (state != 'approved' OR ? = 'approved')",
                       (state, json.dumps(response), status, order_id, state))

    def set_context(self, order_id, context):
        with closing(sqlite3.connect(self.path, timeout=10)) as db, db:
            db.execute("UPDATE payments SET context = ? WHERE order_id = ? AND context IS NULL",
                       (self._encrypt_context(order_id, context), order_id))

    def get(self, order_id, owner=None):
        with closing(sqlite3.connect(self.path, timeout=10)) as db:
            row = db.execute("SELECT state, response, status, context, owner_hash FROM payments WHERE order_id = ?",
                             (order_id,)).fetchone()
        if not row or (owner is not None and row[4] != self._hash(owner)):
            return None
        return {"state": row[0], "response": json.loads(row[1]) if row[1] else None,
                "status": row[2], "context": self._decrypt_context(order_id, row[3]) if row[3] else None}

    def settle(self, order_id, state, response, status):
        with closing(sqlite3.connect(self.path, timeout=10)) as db, db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT state, response, status FROM payments WHERE order_id = ?", (order_id,)).fetchone()
            if row and row[0] == "approved":
                return json.loads(row[1]), row[2], False
            db.execute("UPDATE payments SET state = ?, response = ?, status = ? WHERE order_id = ?",
                       (state, json.dumps(response), status, order_id))
            return response, status, state == "approved"

    def claim_receipt(self, order_id):
        with closing(sqlite3.connect(self.path, timeout=10)) as db, db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT state, response, receipt_lease FROM payments WHERE order_id = ?", (order_id,)).fetchone()
            now = time.time()
            if (not row or row[0] != "approved" or json.loads(row[1]).get("comprobante_enviado")
                    or (row[2] and row[2] > now - 120)):
                return False
            db.execute("UPDATE payments SET receipt_lease = ? WHERE order_id = ?", (now, order_id))
            return True

    def release_receipt(self, order_id):
        with closing(sqlite3.connect(self.path, timeout=10)) as db, db:
            db.execute("UPDATE payments SET receipt_lease = NULL WHERE order_id = ?", (order_id,))

    def admin_list(self, desde_utc=None, hasta_utc=None):
        """Órdenes para el panel de administración (solo tras autorizar al administrador).

        `desde_utc` (inclusive) y `hasta_utc` (exclusivo) son cadenas 'YYYY-MM-DD HH:MM:SS' en UTC,
        el formato de CURRENT_TIMESTAMP de SQLite. No devuelve DNI ni dirección: solo lo necesario
        para consultar compras. Cada fila es una orden (order_id es clave primaria: no hay duplicados).
        """
        sql = "SELECT order_id, state, context, created_at FROM payments"
        condiciones, parametros = [], []
        if desde_utc:
            condiciones.append("created_at >= ?")
            parametros.append(desde_utc)
        if hasta_utc:
            condiciones.append("created_at < ?")
            parametros.append(hasta_utc)
        if condiciones:
            sql += " WHERE " + " AND ".join(condiciones)
        sql += " ORDER BY created_at DESC, rowid DESC"
        with closing(sqlite3.connect(self.path, timeout=10)) as db:
            rows = db.execute(sql, parametros).fetchall()
        resultado = []
        for order_id, state, encrypted_context, created_at in rows:
            legible = True
            try:
                context = self._decrypt_context(order_id, encrypted_context) if encrypted_context else {}
            except Exception:
                context, legible = {}, False
            if not isinstance(context, dict):
                context, legible = {}, False
            cliente = context.get("cliente") if isinstance(context.get("cliente"), dict) else {}
            productos = context.get("productos") if isinstance(context.get("productos"), list) else []
            resultado.append({
                "id": order_id,
                "created_at": created_at,
                "estado": state,
                "legible": legible,
                "email": str(context.get("email") or ""),
                "cliente": str(cliente.get("nombre") or ""),
                # Cada línea del carrito es un empaque: el subtotal es la suma de sus precios
                # sin multiplicar por cantidad, por eso cada línea cuenta como 1 unidad.
                "productos": [{
                    "nombre": str(p.get("medicamento") or p.get("nombre") or "Producto"),
                    "presentacion": str(p.get("presentacion") or ""),
                    "farmacia": str(p.get("farmacia") or ""),
                    "cantidad": 1,
                    "precio": str(p.get("precio") or "0"),
                } for p in productos if isinstance(p, dict)],
                "subtotal": str(context.get("subtotal") or "0"),
                "delivery": str(context.get("delivery") or "0"),
                "total": str(context.get("total") or "0"),
            })
        return resultado

    def pending_receipts(self):
        with closing(sqlite3.connect(self.path, timeout=10)) as db:
            rows = db.execute("SELECT order_id, response FROM payments WHERE state = 'approved'").fetchall()
        return [order_id for order_id, response in rows if not json.loads(response).get("comprobante_enviado")]
