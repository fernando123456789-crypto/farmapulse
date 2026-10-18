import os
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
from pathlib import Path
from unittest.mock import Mock, patch

from identity_security import IdentitySecurity
from payment_ledger import PaymentLedger


class IdentitySecurityTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name) / "security.sqlite3"
        self.store = IdentitySecurity(self.path, "test-secret")
        self.identifiers = {"correo": "test@example.invalid", "dni": "12345678"}

    def test_fifth_failure_is_permanent_and_survives_restart(self):
        for remaining in range(4, -1, -1):
            status = self.store.record_failure(self.identifiers)
            self.assertEqual(status["remaining"], remaining)
            self.assertEqual(status["blocked"], remaining == 0)
        restarted = IdentitySecurity(self.path, "test-secret")
        self.assertTrue(restarted.status({"correo": "test@example.invalid"})["blocked"])
        self.assertTrue(restarted.status({"dni": "12345678"})["blocked"])
        self.assertFalse(restarted.status({"correo": "other@example.invalid"})["blocked"])
        contents = self.path.read_bytes()
        self.assertNotIn(b"12345678", contents)
        self.assertNotIn(b"test@example.invalid", contents)

    def test_parallel_failures_do_not_lose_updates(self):
        with ThreadPoolExecutor(max_workers=8) as pool:
            list(pool.map(lambda _: self.store.record_failure(self.identifiers), range(12)))
        self.assertEqual(self.store.status(self.identifiers), {"blocked": True, "remaining": 0})


class CheckoutIdentityFixture:
    @classmethod
    def setUpClass(cls):
        cls.import_directory = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.import_directory.cleanup)
        with patch.dict(os.environ, {
            "SECRET_KEY": "test-secret",
            "IDENTITY_SECURITY_DB": str(Path(cls.import_directory.name) / "import.sqlite3"),
            "PAYMENTS_DB": str(Path(cls.import_directory.name) / "payments.sqlite3"),
        }):
            import app
        cls.module = app

    def setUp(self):
        m = self.module
        self.real_receipt_sender = m._enviar_comprobante
        self.patch(patch.dict(os.environ, {"MERCADO_PAGO_TEST_APPROVAL": ""}))
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        store = IdentitySecurity(Path(directory.name) / "security.sqlite3", "test-secret")
        self.user = {"id": "test-user", "email": "test@example.invalid"}
        settings = {key: "test" for key in (
            "MERCADO_PAGO_PUBLIC_KEY", "MERCADO_PAGO_ACCESS_TOKEN", "MAIL_HOST", "MAIL_USERNAME",
            "MAIL_PASSWORD", "MAIL_FROM", "RENIEC_TOKEN", "RESEND_API_KEY", "RESEND_FROM",
        )}
        settings["EMAIL_PROVIDER"] = "smtp"
        settings["identity_security"] = store
        settings["MERCADO_PAGO_PUBLIC_KEY"] = "TEST-public-prueba"
        settings["MERCADO_PAGO_ACCESS_TOKEN"] = "TEST-access-prueba"
        settings["payment_ledger"] = PaymentLedger(Path(directory.name) / "payments.sqlite3", "test-secret")
        self.patch(patch.multiple(m, **settings))
        self.patch(patch.object(m.limiter, "enabled", False))
        self.patch(patch.object(m, "_supabase_configurado", return_value=True))
        self.patch(patch.object(m, "auth_obtener_usuario", side_effect=lambda token: self.user))
        self.test_merchant = self.patch(patch.object(m, "_comercio_de_pruebas", return_value=True))
        self.patch(patch.object(m, "_datos_checkout", return_value=([], Decimal("10"), Decimal("5"), Decimal("15"))))
        self.lookup = self.patch(patch.object(m, "consultar_dni_reniec", return_value={"nombre": "OTRA IDENTIDAD"}))
        response = Mock(status_code=201)
        response.json.return_value = {"id": "ord_test_identity"}
        self.payment = self.patch(patch.object(m.requests, "post", return_value=response))
        self.client = m.app.test_client()
        self.headers = {"Authorization": "Bearer test"}
        self.body = {
            "dni": "12345678", "apellidos": "Garcia Lopez", "nombres": "Juan Carlos",
            "telefono": "999999999", "distrito": "San Borja", "direccion": "Av. Prueba 123",
            "place_id": "test/place", "productos": [],
        }
        self.body["direccion_validacion"] = m._VALIDACION_DIRECCION.dumps({
            **{field: self.body[field] for field in ("direccion", "distrito", "place_id")},
            "latitud": -12.107, "longitud": -76.999,
        })

    def patch(self, patcher):
        result = patcher.start()
        self.addCleanup(patcher.stop)
        return result

    def order(self, **changes):
        return self.client.post("/api/checkout/orden", json={**self.body, **changes}, headers=self.headers)

    def exhaust_attempts(self):
        for remaining in range(4, -1, -1):
            response = self.order()
            self.assertEqual(response.status_code, 403 if remaining == 0 else 422)
            self.assertEqual(response.json["intentos_restantes"], remaining)


class CheckoutIdentityTests(CheckoutIdentityFixture, unittest.TestCase):
    def test_blocks_account_email_existing_session_and_dni_on_other_account(self):
        self.exhaust_attempts()
        self.payment.assert_not_called()
        self.lookup.reset_mock()
        self.assertEqual(self.order().status_code, 403)
        self.assertEqual(self.client.get("/api/auth/sesion", headers=self.headers).status_code, 403)
        for endpoint in ("login", "registro"):
            response = self.client.post(f"/api/auth/{endpoint}", json={
                "email": "test@example.invalid", "password": "ClaveSegura123!",
            })
            self.assertEqual(response.status_code, 403)
        self.user = {"id": "new-user", "email": "new@example.invalid"}
        self.assertEqual(self.order(nombres="Otro Nombre").status_code, 403)
        self.lookup.assert_not_called()

    def test_provider_errors_do_not_consume_attempts(self):
        for exception, expected in ((self.module.requests.Timeout(), 504), (ValueError(), 502)):
            self.lookup.side_effect = exception
            self.assertEqual(self.order().status_code, expected)
        status = self.module.identity_security.status({"correo": self.user["email"]})
        self.assertEqual(status["remaining"], 5)
        self.payment.assert_not_called()

    def test_nonexistent_dni_consumes_attempt(self):
        self.lookup.side_effect = LookupError()
        self.assertEqual(self.order().json["intentos_restantes"], 4)

    def test_four_failures_still_allow_correct_identity_without_resetting_count(self):
        for _ in range(4):
            self.assertEqual(self.order().status_code, 422)
        self.lookup.return_value = {"nombre": "GARCIA LOPEZ JUAN CARLOS"}
        self.assertEqual(self.order().status_code, 200)
        self.assertEqual(self.module.identity_security.status({"correo": self.user["email"]})["remaining"], 1)

    def test_previously_issued_order_cannot_be_paid_after_block(self):
        self.lookup.return_value = {"nombre": "GARCIA LOPEZ JUAN CARLOS"}
        signature = self.order().json["orden_firma"]
        self.lookup.return_value = {"nombre": "OTRA IDENTIDAD"}
        self.exhaust_attempts()
        self.payment.reset_mock()
        response = self.client.post("/api/checkout/pagar", json={
            **self.body, "token": "a" * 32, "orden_firma": signature,
                "payment_method_id": "visa", "payment_type_id": "credit_card", "installments": 1,
        }, headers=self.headers)
        self.assertEqual(response.status_code, 403)
        self.payment.assert_not_called()

    def test_unrelated_person_with_same_full_name_is_not_blocked(self):
        self.exhaust_attempts()
        self.user = {"id": "other-user", "email": "other@example.invalid"}
        self.lookup.return_value = {"nombre": "GARCIA LOPEZ JUAN CARLOS"}
        self.assertEqual(self.order(dni="87654321").status_code, 200)

    def test_storage_unavailable_fails_closed(self):
        import sqlite3
        with patch.object(self.module.identity_security, "status", side_effect=sqlite3.OperationalError()):
            self.assertEqual(self.order().status_code, 503)
        self.lookup.assert_not_called()
        self.payment.assert_not_called()

    def test_verified_customer_can_still_complete_payment(self):
        self.lookup.return_value = {"nombre": "GARCIA LOPEZ JUAN CARLOS"}
        signature = self.order().json["orden_firma"]
        self.payment.return_value.json.return_value = {
            "id": "ORDTST" + "A" * 26, "type": "online", "status": "processed", "status_detail": "accredited",
            "currency": "PEN", "total_amount": "15.00", "total_paid_amount": "15.00",
            "external_reference": self.module._COTIZACIONES.loads(signature)["id"],
            "transactions": {"payments": [{"id": "PAY" + "B" * 26, "status": "processed", "status_detail": "accredited",
                "amount": "15.00", "paid_amount": "15.00", "payment_method": {"id": "visa", "type": "credit_card"}}]},
        }
        with patch.object(self.module, "_enviar_comprobante") as receipt:
            response = self.client.post("/api/checkout/pagar", json={
                **self.body, "token": "a" * 32, "orden_firma": signature,
                "payment_method_id": "visa", "payment_type_id": "credit_card", "installments": 1,
            }, headers=self.headers)
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json["pago_confirmado"])
        receipt.assert_called_once()


if __name__ == "__main__":
    unittest.main()
