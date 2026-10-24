"""Aislamiento común: una unitaria no debe contactar servicios ni bases reales."""

import unittest
from unittest.mock import patch


class OfflineUnitTestCase(unittest.TestCase):
    """Bloquea efectos externos y restaura cada parche después de cada prueba."""

    def setUp(self):
        super().setUp()
        for target in (
            "socket.socket.connect",
            "socket.create_connection",
            "sqlite3.connect",
            "smtplib.SMTP",
            "smtplib.SMTP_SSL",
        ):
            self.enterContext(patch(
                target,
                side_effect=AssertionError(
                    f"Efecto externo no permitido en una prueba unitaria: {target}"
                ),
            ))
