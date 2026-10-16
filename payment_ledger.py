"""Control persistente de envíos de cargos para evitar cobros duplicados."""

import hashlib
import hmac
import json
import sqlite3
import time
from contextlib import closing
from pathlib import Path


class PaymentLedger:
    def __init__(self, path, secret):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.secret = secret.encode()
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute("""CREATE TABLE IF NOT EXISTS payments (
                order_id TEXT PRIMARY KEY, token_hash TEXT NOT NULL UNIQUE,
                device_hash TEXT NOT NULL, state TEXT NOT NULL,
                response TEXT, status INTEGER, owner_hash TEXT, context TEXT
            )""")
            if "owner_hash" not in {row[1] for row in db.execute("PRAGMA table_info(payments)")}:
                db.execute("ALTER TABLE payments ADD COLUMN owner_hash TEXT")
            if "context" not in {row[1] for row in db.execute("PRAGMA table_info(payments)")}:
                db.execute("ALTER TABLE payments ADD COLUMN context TEXT")
            if "receipt_lease" not in {row[1] for row in db.execute("PRAGMA table_info(payments)")}:
                db.execute("ALTER TABLE payments ADD COLUMN receipt_lease REAL")

    def _hash(self, value):
        return hmac.new(self.secret, value.encode(), hashlib.sha256).hexdigest()

    def claim(self, order_id, token, device, owner):
        token_hash, device_hash = self._hash(token), self._hash(device)
        with closing(sqlite3.connect(self.path, timeout=10)) as db, db:
            db.execute("BEGIN IMMEDIATE")
            existing = db.execute(
                "SELECT order_id, token_hash, device_hash, state, response, status FROM payments "
                "WHERE order_id = ? OR token_hash = ?", (order_id, token_hash),
            ).fetchall()
            if existing:
                if len(existing) != 1 or existing[0][:3] != (order_id, token_hash, device_hash):
                    return {"ok": False, "estado": "conflicto", "error": "La orden o el token ya se utilizaron en otro intento de pago"}, 409
                _, _, _, state, response, status = existing[0]
                if response:
                    return json.loads(response), status
                return {"ok": False, "estado": "procesando", "error": "Este pago ya se está procesando. No generes otro cobro"}, 409
            pending = db.execute("SELECT order_id FROM payments WHERE owner_hash = ? AND state IN ('processing', 'unknown', 'pending')",
                                 (self._hash(owner),)).fetchone()
            if pending:
                return {"ok": False, "estado": "sin_confirmar", "referencia": pending[0],
                        "error": "Ya hay un pago pendiente de confirmación. Contacta a soporte antes de pagar otra vez"}, 409
            db.execute("INSERT INTO payments (order_id, token_hash, device_hash, owner_hash, state) VALUES (?, ?, ?, ?, 'processing')",
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
                       (json.dumps(context), order_id))

    def get(self, order_id, owner=None):
        with closing(sqlite3.connect(self.path, timeout=10)) as db:
            row = db.execute("SELECT state, response, status, context, owner_hash FROM payments WHERE order_id = ?",
                             (order_id,)).fetchone()
        if not row or (owner is not None and row[4] != self._hash(owner)):
            return None
        return {"state": row[0], "response": json.loads(row[1]) if row[1] else None,
                "status": row[2], "context": json.loads(row[3]) if row[3] else None}

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

    def pending_receipts(self):
        with closing(sqlite3.connect(self.path, timeout=10)) as db:
            rows = db.execute("SELECT order_id, response FROM payments WHERE state = 'approved'").fetchall()
        return [order_id for order_id, response in rows if not json.loads(response).get("comprobante_enviado")]
