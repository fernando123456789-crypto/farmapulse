import os
import unittest
from unittest.mock import patch

from test_identity_security import CheckoutIdentityFixture


class AuthConfirmationTests(CheckoutIdentityFixture, unittest.TestCase):
    def setUp(self):
        super().setUp()
        self.payment.return_value.status_code = 200
        self.payment.return_value.json.return_value = {}
        self.patch(patch.dict(os.environ, {"APP_BASE_URL": ""}))

    def resend(self, body=None):
        return self.client.post("/api/auth/reenviar-confirmacion", base_url="https://127.0.0.1:5443",
                                json=body if body is not None else {"email": " Buyer@Example.com "})

    def test_resend_uses_signup_and_correct_https_redirect_parameter(self):
        result = self.resend()
        self.assertEqual(result.status_code, 200)
        self.assertNotIn("enviado", result.json["mensaje"])
        args = self.payment.call_args
        self.assertTrue(args.args[0].endswith("/auth/v1/resend"))
        self.assertEqual(args.kwargs["json"], {"type": "signup", "email": "buyer@example.com"})
        self.assertEqual(args.kwargs["params"], {"redirect_to": "https://127.0.0.1:5443/comparador"})

    def test_user_cannot_override_redirect(self):
        self.resend({"email": "buyer@example.com", "redirect_to": "https://attacker.invalid"})
        self.assertEqual(self.payment.call_args.kwargs["params"]["redirect_to"], "https://127.0.0.1:5443/comparador")

    def test_invalid_email_or_body_never_contacts_supabase(self):
        for body in ({"email": []}, {"email": "invalid"}, ["invalid"], {"email": "a\nb@example.com"}):
            self.assertEqual(self.resend(body).status_code, 400)
        self.payment.assert_not_called()

    def test_provider_rate_limit_is_not_reported_as_success(self):
        self.payment.return_value.status_code = 429
        self.payment.return_value.json.return_value = {"code": "over_email_send_rate_limit"}
        result = self.resend()
        self.assertEqual(result.status_code, 429)
        self.assertFalse(result.json["ok"])

    def test_provider_failure_does_not_expose_details_or_claim_delivery(self):
        self.payment.return_value.status_code = 500
        self.payment.return_value.json.return_value = {"message": "internal private smtp details"}
        result = self.resend()
        self.assertEqual(result.status_code, 502)
        self.assertFalse(result.json["ok"])
        self.assertNotIn("private", str(result.json))

    def test_registration_does_not_claim_success_when_email_provider_fails(self):
        self.payment.return_value.status_code = 429
        self.payment.return_value.json.return_value = {"code": "over_email_send_rate_limit"}
        result = self.client.post("/api/auth/registro", json={"email": "buyer@example.com", "password": "Abcd1234!efgh"})
        self.assertEqual(result.status_code, 429)
        self.assertFalse(result.json["ok"])

    def test_existing_confirmed_user_is_not_automatically_logged_in(self):
        self.payment.return_value.json.return_value = {"user": {"identities": []}}
        result = self.client.post("/api/auth/registro", json={"email": "buyer@example.com", "password": "Abcd1234!efgh"})
        self.assertTrue(result.json["requiere_confirmacion"])
        self.assertIsNone(result.json["access_token"])

    def test_rate_limiter_prevents_repeated_mail_requests(self):
        with patch.object(self.module.limiter, "enabled", True):
            self.resend({"email": "limit-test@example.com"})
            result = self.resend({"email": "limit-test@example.com"})
        self.assertEqual(result.status_code, 429)
        self.payment.assert_called_once()
