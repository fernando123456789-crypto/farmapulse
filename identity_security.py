"""Persistencia local de intentos y bloqueos de identidad."""

import hashlib
import hmac
import sqlite3
import time
from contextlib import closing
from pathlib import Path


class IdentitySecurity:
    MAX_FAILURES = 5

    def __init__(self, path, secret):
        self.path = Path(path)
        self.secret = secret.encode("utf-8")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with closing(self._connect()) as connection, connection:
            connection.execute("""
                CREATE TABLE IF NOT EXISTS identity_attempts (
                    identifier TEXT PRIMARY KEY,
                    failures INTEGER NOT NULL DEFAULT 0,
                    blocked INTEGER NOT NULL DEFAULT 0
                )
            """)
            connection.execute("""CREATE TABLE IF NOT EXISTS revoked_tokens (
                token_hash TEXT PRIMARY KEY, expires REAL NOT NULL
            )""")

    def revoke_token(self, token):
        key = self._keys({"sesion": token})[0]
        with closing(self._connect()) as connection, connection:
            now = time.time()
            connection.execute("DELETE FROM revoked_tokens WHERE expires <= ?", (now,))
            connection.execute("INSERT OR REPLACE INTO revoked_tokens VALUES (?, ?)", (key, now + 30 * 86400))

    def token_revoked(self, token):
        key = self._keys({"sesion": token})[0]
        with closing(self._connect()) as connection:
            return connection.execute(
                "SELECT 1 FROM revoked_tokens WHERE token_hash = ? AND expires > ?", (key, time.time()),
            ).fetchone() is not None

    def _connect(self):
        return sqlite3.connect(self.path, timeout=10)

    def _keys(self, identifiers):
        return tuple({
            hmac.new(self.secret, f"{kind}:{value}".encode("utf-8"), hashlib.sha256).hexdigest()
            for kind, value in identifiers.items() if value
        })

    def _status(self, connection, keys):
        if not keys:
            return {"blocked": False, "remaining": self.MAX_FAILURES}
        rows = [connection.execute(
            "SELECT failures, blocked FROM identity_attempts WHERE identifier = ?", (key,),
        ).fetchone() for key in keys]
        failures = max((row[0] for row in rows if row), default=0)
        blocked = any(row[1] for row in rows if row)
        return {"blocked": bool(blocked), "remaining": max(0, self.MAX_FAILURES - failures)}

    def status(self, identifiers):
        with closing(self._connect()) as connection:
            return self._status(connection, self._keys(identifiers))

    def record_failure(self, identifiers):
        keys = self._keys(identifiers)
        with closing(self._connect()) as connection, connection:
            connection.execute("BEGIN IMMEDIATE")
            status = self._status(connection, keys)
            if not status["blocked"]:
                connection.executemany(
                    "INSERT INTO identity_attempts (identifier, failures) VALUES (?, 1) "
                    "ON CONFLICT(identifier) DO UPDATE SET failures = MIN(failures + 1, ?)",
                    ((key, self.MAX_FAILURES) for key in keys),
                )
                status = self._status(connection, keys)
            if status["blocked"] or status["remaining"] == 0:
                connection.executemany(
                    "INSERT INTO identity_attempts (identifier, failures, blocked) VALUES (?, ?, 1) "
                    "ON CONFLICT(identifier) DO UPDATE SET blocked = 1, failures = excluded.failures",
                    ((key, self.MAX_FAILURES) for key in keys),
                )
                return {"blocked": True, "remaining": 0}
            return status
