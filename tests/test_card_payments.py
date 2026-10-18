from copy import deepcopy
import hashlib
import os
import hmac
import smtplib
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
from pathlib import Path
from unittest.mock import Mock, patch

from payment_ledger import PaymentLedger
from test_identity_security import CheckoutIdentityFixture


class MercadoPagoTests(CheckoutIdentityFixture, unittest.TestCase):
    def test_approval_scenario_requires_verified_test_merchant(self):
        with patch.dict(os.environ, {"MERCADO_PAGO_TEST_APPROVAL": "1"}):
            with patch.object(self.module, "_comercio_de_pruebas", return_value=False):
                self.assertEqual(self.order().status_code, 503)
            with patch.object(self.module, "_comercio_de_pruebas", return_value=True):
                data = self.order().json
                self.assertEqual(data["pagador"]["nombre_tarjeta_prueba"], "APRO-AUTH")
                self.assertEqual(data["pagador"]["nombre"], self.body["nombres"] + " " + self.body["apellidos"])

    def test_test_merchant_detection_is_verified_with_provider(self):
        verifier = self.real_merchant_verifier
        self.module._consultar_comercio_de_pruebas.cache_clear()
        with patch.object(self.module.requests, "get") as get:
            get.return_value.json.return_value = {"site_id": "MPE", "tags": ["test_user"]}
            self.assertTrue(verifier("sandbox-token"))
            self.assertTrue(verifier("sandbox-token"))
            self.assertEqual(get.call_count, 1)
            get.return_value.json.return_value = {"site_id": "MPE", "tags": []}
            self.assertFalse(verifier("production-token"))
            get.return_value.json.return_value = {"site_id": "MPE", "tags": "not_test_user"}
            self.assertFalse(verifier("malformed-tags"))
            get.side_effect = self.module.requests.Timeout()
            self.assertFalse(verifier("unavailable-merchant"))
            get.side_effect = None
            get.return_value.json.return_value = {"site_id": "MPE", "tags": ["test_user"]}
            self.assertTrue(verifier("unavailable-merchant"), "Un fallo de red no debe bloquear las pruebas hasta reiniciar")
        self.module._consultar_comercio_de_pruebas.cache_clear()

    def setUp(self):
        self.real_merchant_verifier = self.module._comercio_de_pruebas
        super().setUp()
        self.lookup.return_value = {"nombre": "GARCIA LOPEZ JUAN CARLOS"}
        order = self.order()
        self.assertEqual(order.status_code, 200)
        self.reference = order.json["orden_id"]
        self.payload = {**self.body, "orden_firma": order.json["orden_firma"], "token": "a" * 32,
                        "payment_method_id": "visa", "payment_type_id": "credit_card", "installments": 1, "issuer_id": "123"}
        self.provider_id = "ORDTST" + "A" * 26
        self.approved = {"id": self.provider_id, "type": "online", "status": "processed", "status_detail": "accredited",
                         "currency": "PEN", "total_amount": "15.00", "total_paid_amount": "15.00",
                         "external_reference": self.reference, "transactions": {"payments": [{
                             "id": "PAY" + "B" * 26, "amount": "15.00", "paid_amount": "15.00",
                             "status": "processed", "status_detail": "accredited",
                             "payment_method": {"id": "visa", "type": "credit_card"},
                         }]}}
        self.payment.return_value.status_code = 201
        self.payment.return_value.json.return_value = deepcopy(self.approved)
        self.receipt = self.patch(patch.object(self.module, "_enviar_comprobante"))

    def pay(self, **changes):
        return self.client.post("/api/checkout/pagar", json={**self.payload, **changes}, headers=self.headers)

    def test_order_returns_verified_identity_for_card_tokenization(self):
        order = self.order()
        self.assertEqual(order.json["pagador"], {
            "nombre": self.body["nombres"] + " " + self.body["apellidos"], "dni": self.body["dni"],
        })

    def test_live_or_unverifiable_merchant_cannot_create_or_charge_an_order(self):
        self.test_merchant.return_value = False
        self.lookup.reset_mock()
        with patch.object(self.module.payment_ledger, "claim") as claim:
            for response in (self.order(), self.pay()):
                self.assertEqual(response.status_code, 503)
                self.assertFalse(response.json["ok"])
            claim.assert_not_called()
        self.lookup.assert_not_called()
        self.payment.assert_not_called()
        self.receipt.assert_not_called()

    def test_live_merchant_does_not_enable_card_entry(self):
        self.test_merchant.return_value = False
        self.assertFalse(self.client.get("/api/config").json["pasarela_configurada"])
        self.payment.assert_not_called()

    def test_resend_configuration_enables_receipts_without_smtp_credentials(self):
        with patch.multiple(self.module, EMAIL_PROVIDER="resend", RESEND_API_KEY="re_test_key",
                            RESEND_FROM="FarmaPulse <recibos@example.com>", MAIL_HOST="",
                            MAIL_USERNAME="", MAIL_PASSWORD="", MAIL_FROM=""):
            self.assertTrue(self.module._pagos_configurados())
            self.assertTrue(self.client.get("/api/config").json["pasarela_configurada"])

    def test_resend_requires_both_api_key_and_verified_sender_configuration(self):
        with patch.multiple(self.module, EMAIL_PROVIDER="resend", RESEND_API_KEY="", RESEND_FROM=""):
            self.assertFalse(self.module._pagos_configurados())

    def test_receipt_can_use_resend_https_api(self):
        response = Mock()
        with patch.multiple(self.module, EMAIL_PROVIDER="resend", RESEND_API_KEY="re_test_key",
                            RESEND_FROM="FarmaPulse <recibos@example.com>"), \
                patch.object(self.module.requests, "post", return_value=response) as send:
            self.real_receipt_sender(
                "buyer@example.com", "Comprador", "12345678",
                {"nombre": "Comprador", "dni": "12345678", "direccion": "Calle 1", "distrito": "San Borja"},
                [{"medicamento": "Producto", "presentacion": "Caja", "farmacia": "Farmacia", "precio": "10.00"}],
                Decimal("10"), Decimal("5"), Decimal("15"), "PAY-test",
            )
        send.assert_called_once()
        args, kwargs = send.call_args
        self.assertEqual(args[0], "https://api.resend.com/emails")
        self.assertEqual(kwargs["headers"]["Authorization"], "Bearer re_test_key")
        self.assertEqual(kwargs["headers"]["Idempotency-Key"], "receipt/PAY-test")
        self.assertEqual(kwargs["json"]["from"], "FarmaPulse <recibos@example.com>")
        self.assertEqual(kwargs["json"]["to"], ["buyer@example.com"])
        self.assertIn("Comprobante de compra FarmaPulse", kwargs["json"]["subject"])
        response.raise_for_status.assert_called_once()

    def test_resend_http_error_is_reported_to_receipt_retry_logic(self):
        response = Mock()
        response.raise_for_status.side_effect = self.module.requests.HTTPError("provider rejected request")
        with patch.multiple(self.module, EMAIL_PROVIDER="resend", RESEND_API_KEY="re_test_key",
                            RESEND_FROM="FarmaPulse <recibos@example.com>"), \
                patch.object(self.module.requests, "post", return_value=response):
            with self.assertRaises(self.module.requests.HTTPError):
                self.real_receipt_sender(
                    "buyer@example.com", "Comprador", "12345678",
                    {"nombre": "Comprador", "dni": "12345678", "direccion": "Calle 1", "distrito": "San Borja"},
                    [{"medicamento": "Producto", "presentacion": "Caja", "farmacia": "Farmacia", "precio": "10.00"}],
                    Decimal("10"), Decimal("5"), Decimal("15"), "PAY-test",
                )
        response.raise_for_status.assert_called_once()

    def test_existing_smtp_receipt_path_remains_available(self):
        smtp = Mock()
        smtp.__enter__ = Mock(return_value=smtp)
        smtp.__exit__ = Mock(return_value=False)
        with patch.multiple(self.module, EMAIL_PROVIDER="smtp", MAIL_HOST="smtp.example.com",
                            MAIL_PORT=587, MAIL_USERNAME="sender@example.com", MAIL_PASSWORD="password",
                            MAIL_FROM="FarmaPulse <sender@example.com>"), \
                patch.object(self.module.smtplib, "SMTP", return_value=smtp) as connect:
            self.real_receipt_sender(
                "buyer@example.com", "Comprador", "12345678",
                {"nombre": "Comprador", "dni": "12345678", "direccion": "Calle 1", "distrito": "San Borja"},
                [{"medicamento": "Producto", "presentacion": "Caja", "farmacia": "Farmacia", "precio": "10.00"}],
                Decimal("10"), Decimal("5"), Decimal("15"), "PAY-test",
            )
        connect.assert_called_once_with("smtp.example.com", 587, timeout=15)
        smtp.starttls.assert_called_once()
        smtp.login.assert_called_once_with("sender@example.com", "password")
        smtp.send_message.assert_called_once()

    def test_resend_http_failure_leaves_approved_receipt_pending_for_retry(self):
        with patch.multiple(self.module, EMAIL_PROVIDER="resend", RESEND_API_KEY="re_test_key",
                            RESEND_FROM="FarmaPulse <recibos@example.com>"):
            self.receipt.side_effect = self.module.requests.HTTPError("provider rejected request")
            result = self.pay()
        self.assertTrue(result.json["pago_confirmado"])
        self.assertFalse(result.json["comprobante_enviado"])
        self.assertEqual(self.module.payment_ledger.pending_receipts(), [self.reference])

    def test_card_payment_uses_merchant_credentials_without_a_buyer_mp_account(self):
        self.user["email"] = "cliente-sin-cuenta-mp@example.invalid"
        order = self.order().json
        self.approved["external_reference"] = order["orden_id"]
        self.payment.return_value.json.return_value = deepcopy(self.approved)
        response = self.pay(orden_firma=order["orden_firma"])
        self.assertEqual(response.status_code, 200)
        sent = self.payment.call_args.kwargs
        self.assertEqual(sent["headers"]["Authorization"], "Bearer TEST-access-prueba")
        self.assertEqual(set(sent["json"]["payer"]), {"email", "first_name", "last_name", "identification"})
        self.assertEqual(sent["json"]["payer"]["email"], self.user["email"])
        self.assertNotIn("redirect_url", response.json)
        self.assertTrue(self.receipt.call_args.args[3]["compra_prueba"])
        self.assertTrue(self.module.payment_ledger.get(order["orden_id"])["context"]["modo_prueba"])

    def test_approved_payment_and_duplicate_only_charge_once(self):
        self.payment.assert_not_called()
        first, repeated = self.pay(transaction_amount=99999), self.pay()
        self.assertEqual(first.status_code, 200)
        self.assertEqual(first.json["estado"], "aprobado")
        self.assertTrue(first.json["pago_confirmado"])
        self.assertEqual(first.json, repeated.json)
        self.payment.assert_called_once()
        self.receipt.assert_called_once()
        self.assertEqual(self.receipt.call_args.args[0], self.user["email"])
        self.assertEqual(self.payment.call_args.args[0], "https://api.mercadopago.com/v1/orders")
        sent = self.payment.call_args.kwargs
        self.assertEqual(sent["headers"]["X-Idempotency-Key"], self.reference)
        self.assertEqual(sent["json"]["total_amount"], "15.00")
        self.assertEqual(sent["json"]["payer"]["email"], self.user["email"])
        self.assertEqual(sent["json"]["payer"]["identification"]["number"], self.body["dni"])
        self.assertEqual(sent["json"]["config"]["online"]["transaction_security"]["validation"], "on_fraud_risk")

    def test_rejected_payment_does_not_send_receipt(self):
        self.payment.return_value.json.return_value = {**self.approved, "status": "failed"}
        result = self.pay()
        self.assertEqual(result.status_code, 402)
        self.assertEqual(result.json["estado"], "rechazado")
        self.receipt.assert_not_called()

    def test_provider_http_error_does_not_fake_payment(self):
        self.payment.return_value.status_code = 400
        self.payment.return_value.json.return_value = {"error": "bad_request"}
        self.assertFalse(self.pay().json["ok"])
        self.receipt.assert_not_called()

    def test_timeout_does_not_retry_or_claim_rejection(self):
        self.payment.side_effect = self.module.requests.Timeout()
        self.assertEqual(self.pay().json["estado"], "sin_confirmar")
        self.pay()
        other = self.order()
        result = self.pay(token="b" * 32, orden_firma=other.json["orden_firma"])
        self.assertEqual(result.status_code, 409)
        self.payment.assert_called_once()

    def assert_invalid_result(self, field, value):
        self.payment.return_value.json.return_value[field] = value
        result = self.pay()
        self.assertFalse(result.json["ok"])
        self.assertEqual(result.json["estado"], "sin_confirmar")
        self.receipt.assert_not_called()

    def test_wrong_amount_is_not_approved(self):
        self.assert_invalid_result("total_amount", "1.00")

    def test_wrong_currency_is_not_approved(self):
        self.assert_invalid_result("currency", "USD")

    def test_wrong_reference_is_not_approved(self):
        self.assert_invalid_result("external_reference", "other-order")

    def test_non_card_payment_is_not_approved(self):
        self.payment.return_value.json.return_value["transactions"]["payments"][0]["payment_method"]["type"] = "ticket"
        self.assertEqual(self.pay().json["estado"], "sin_confirmar")
        self.receipt.assert_not_called()

    def test_uncaptured_payment_is_not_approved(self):
        self.assert_invalid_result("total_paid_amount", "0.00")

    def test_invalid_payment_data_does_not_call_provider(self):
        for changes in ({"payment_type_id": "ticket"}, {"payment_type_id": None}, {"token": []}, {"token": "not-a-token"}, {"installments": 0},
                        {"installments": True}, {"issuer_id": "https://example.invalid"}):
            self.assertEqual(self.pay(**changes).status_code, 400)
        self.payment.assert_not_called()

    def test_signed_order_belongs_to_authenticated_user(self):
        self.user = {"id": "other-user", "email": self.user["email"]}
        self.assertEqual(self.pay().status_code, 400)
        self.payment.assert_not_called()

    def test_receipt_failure_preserves_approved_payment(self):
        self.receipt.side_effect = smtplib.SMTPException()
        result = self.pay()
        self.assertTrue(result.json["pago_confirmado"])
        self.assertFalse(result.json["comprobante_enviado"])
        self.assertTrue(self.pay().json["pago_confirmado"])
        self.payment.assert_called_once()

    def test_failed_receipt_is_retried_without_charging_again(self):
        self.receipt.side_effect = smtplib.SMTPException()
        self.pay(email="attacker@example.invalid")
        self.assertEqual(self.module.payment_ledger.pending_receipts(), [self.reference])
        self.receipt.side_effect = None
        result = self.client.get(f"/api/checkout/estado/{self.reference}", headers=self.headers)
        self.assertTrue(result.json["comprobante_enviado"])
        self.assertEqual(self.receipt.call_args.args[0], self.user["email"])
        self.assertEqual(self.module.payment_ledger.pending_receipts(), [])
        self.payment.assert_called_once()

    def test_mismatched_transaction_is_not_approved(self):
        self.payment.return_value.json.return_value["transactions"]["payments"][0]["paid_amount"] = "1.00"
        self.assertEqual(self.pay().json["estado"], "sin_confirmar")
        self.receipt.assert_not_called()

    def test_processed_order_with_pending_transaction_is_not_approved(self):
        self.payment.return_value.json.return_value["transactions"]["payments"][0]["status"] = "processing"
        self.assertEqual(self.pay().json["estado"], "sin_confirmar")
        self.receipt.assert_not_called()

    def test_invalid_bank_url_is_never_sent_to_browser(self):
        self.pending_payment()
        data = self.payment.return_value.json.return_value
        data["transactions"]["payments"][0]["payment_method"]["transaction_security"]["url"] = "https://attacker.example"
        with self.module.app.app_context():
            result, _ = self.module._procesar_resultado_mercado_pago(self.reference, data)
        self.assertNotIn("challenge_url", result.json)

    def test_missing_access_token_disables_payment_and_never_leaks_secret(self):
        config = self.client.get("/api/config").json
        self.assertIn("mercado_pago_public_key", config)
        self.assertNotIn("MERCADO_PAGO_ACCESS_TOKEN", str(config))
        with patch.object(self.module, "MERCADO_PAGO_ACCESS_TOKEN", ""):
            self.assertEqual(self.pay().status_code, 503)
            self.assertFalse(self.client.get("/api/config").json["pasarela_configurada"])
        self.payment.assert_not_called()

    def pending_payment(self):
        self.payment.return_value.json.return_value = {
            **deepcopy(self.approved), "status": "action_required", "status_detail": "pending_challenge",
        }
        payment = self.payment.return_value.json.return_value["transactions"]["payments"][0]
        payment.update(status="action_required", status_detail="pending_challenge")
        payment["payment_method"]["transaction_security"] = {"url": "https://www.mercadopago.com.pe/auth/test"}
        result = self.pay()
        self.assertEqual(result.status_code, 202)
        self.assertEqual(result.json["estado"], "pendiente")
        self.assertFalse(result.json["pago_confirmado"])
        self.receipt.assert_not_called()
        return result

    def test_pending_challenge_is_confirmed_by_backend_status_query(self):
        self.pending_payment()
        response = Mock()
        response.json.return_value = self.approved
        with patch.object(self.module.requests, "get", return_value=response) as provider:
            result = self.client.get(f"/api/checkout/estado/{self.reference}", headers=self.headers)
        self.assertEqual(result.json["estado"], "aprobado")
        self.assertTrue(result.json["pago_confirmado"])
        self.assertTrue(provider.call_args.args[0].endswith("/" + self.provider_id))
        self.receipt.assert_called_once()

    def test_other_user_cannot_query_payment(self):
        self.pending_payment()
        self.user = {"id": "other", "email": "other@example.invalid"}
        with patch.object(self.module.requests, "get") as provider:
            self.assertEqual(self.client.get(f"/api/checkout/estado/{self.reference}", headers=self.headers).status_code, 404)
        provider.assert_not_called()

    def webhook(self, valid=True):
        manifest = f"id:{self.provider_id};request-id:test-request;ts:1700000000;"
        digest = hmac.new(b"test-webhook-secret", manifest.encode(), hashlib.sha256).hexdigest() if valid else "invalid"
        return self.client.post(f"/api/pagos/mercadopago/webhook?data.id={self.provider_id}", json={"status": "approved"},
                                headers={"x-request-id": "test-request", "x-signature": f"ts=1700000000,v1={digest}"})

    def test_unsigned_webhook_cannot_confirm_payment(self):
        self.pending_payment()
        with patch.object(self.module, "MERCADO_PAGO_WEBHOOK_SECRET", "test-webhook-secret"), patch.object(self.module.requests, "get") as provider:
            self.assertEqual(self.webhook(valid=False).status_code, 401)
        provider.assert_not_called()
        self.receipt.assert_not_called()

    def test_signed_webhook_queries_provider_and_only_sends_one_receipt(self):
        self.pending_payment()
        response = Mock()
        response.json.return_value = self.approved
        with patch.object(self.module, "MERCADO_PAGO_WEBHOOK_SECRET", "test-webhook-secret"), patch.object(self.module.requests, "get", return_value=response):
            self.assertEqual(self.webhook().status_code, 200)
            self.assertEqual(self.webhook().status_code, 200)
        self.receipt.assert_called_once()
        self.assertTrue(self.module.payment_ledger.get(self.reference)["response"]["pago_confirmado"])

    def test_webhook_body_is_not_used_as_payment_approval(self):
        self.pending_payment()
        response = Mock()
        response.json.return_value = {**self.approved, "status": "failed"}
        with patch.object(self.module, "MERCADO_PAGO_WEBHOOK_SECRET", "test-webhook-secret"), patch.object(self.module.requests, "get", return_value=response):
            self.assertEqual(self.webhook().status_code, 200)
        self.assertFalse(self.module.payment_ledger.get(self.reference)["response"]["pago_confirmado"])
        self.receipt.assert_not_called()


class PaymentLedgerTests(unittest.TestCase):
    def test_concurrent_receipt_delivery_can_only_be_claimed_once(self):
        with tempfile.TemporaryDirectory() as directory:
            ledger = PaymentLedger(Path(directory) / "payments.sqlite3", "test-secret")
            ledger.claim("order", "token", "", "user")
            ledger.finish("order", "approved", {"comprobante_enviado": False}, 200)
            with ThreadPoolExecutor(max_workers=8) as pool:
                claims = list(pool.map(lambda _: ledger.claim_receipt("order"), range(12)))
            self.assertEqual(sum(claims), 1)
            ledger.release_receipt("order")
            self.assertTrue(ledger.claim_receipt("order"))

    def test_concurrent_requests_claim_one_payment_and_persist_result(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "payments.sqlite3"
            ledger = PaymentLedger(path, "test-secret")
            with ThreadPoolExecutor(max_workers=8) as pool:
                claims = list(pool.map(lambda _: ledger.claim("order", "token", "", "user"), range(12)))
            self.assertEqual(sum(result is None for result in claims), 1)
            ledger.finish("order", "approved", {"ok": True, "pago_id": "12345"}, 200)
            result, status = PaymentLedger(path, "test-secret").claim("order", "token", "", "user")
            self.assertEqual(status, 200)
            self.assertTrue(result["ok"])
