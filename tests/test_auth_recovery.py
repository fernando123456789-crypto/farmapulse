import os
import unittest
from unittest.mock import Mock, patch

from test_identity_security import CheckoutIdentityFixture


class AuthRecoveryTests(CheckoutIdentityFixture, unittest.TestCase):
    def setUp(self):
        super().setUp()
        self.payment.return_value.status_code = 200
        self.payment.return_value.json.return_value = {}
        self.patch(patch.dict(os.environ, {"APP_BASE_URL": ""}))
        response = Mock(status_code=200)
        response.json.return_value = self.user
        self.update = self.patch(patch.object(self.module.requests, "put", return_value=response))

    def recover(self, body=None):
        return self.client.post("/api/auth/recuperar-contrasena", base_url="https://127.0.0.1:5443",
                                json=body if body is not None else {"email": " Buyer@Example.com "})

    def change(self, body=None, headers=None):
        return self.client.post("/api/auth/nueva-contrasena", headers=self.headers if headers is None else headers,
                                json=body if body is not None else {"password": "ClaveNueva123!"})

    def test_recovery_uses_server_https_redirect_without_password_or_tokens(self):
        result = self.recover({"email": " Buyer@Example.com ", "redirect_to": "https://attacker.invalid"})
        self.assertEqual(result.status_code, 200)
        self.assertTrue(result.json["ok"])
        args = self.payment.call_args
        self.assertTrue(args.args[0].endswith("/auth/v1/recover"))
        self.assertEqual(args.kwargs["json"], {"email": "buyer@example.com"})
        self.assertEqual(args.kwargs["params"], {"redirect_to": "https://127.0.0.1:5443/comparador"})
        self.assertNotIn("access_token", result.json)

    def test_malformed_recovery_never_contacts_provider(self):
        for body in (["email"], {"email": []}, {"email": "invalid"}, {"email": "a\nb@example.com"}):
            self.assertEqual(self.recover(body).status_code, 400)
        self.payment.assert_not_called()

    def test_blocked_email_cannot_bypass_identity_block_with_recovery(self):
        for _ in range(5):
            self.module.identity_security.record_failure({"correo": "buyer@example.com"})
        result = self.recover()
        self.assertEqual(result.status_code, 200)
        self.assertNotIn("bloqueado", str(result.json))
        self.payment.assert_not_called()

    def test_smtp_failure_is_not_claimed_as_delivery(self):
        self.payment.return_value.status_code = 500
        self.payment.return_value.json.return_value = {"msg": "private SMTP failure"}
        result = self.recover()
        self.assertEqual(result.status_code, 502)
        self.assertFalse(result.json["ok"])
        self.assertIn("recuperación", result.json["error"])
        self.assertNotIn("private", str(result.json))

    def test_recovery_provider_and_app_limits_are_preserved(self):
        self.payment.return_value.status_code = 429
        self.payment.return_value.json.return_value = {"code": "over_email_send_rate_limit"}
        self.assertEqual(self.recover().status_code, 429)
        self.payment.reset_mock()
        with patch.object(self.module.limiter, "enabled", True):
            self.recover()
            self.assertEqual(self.recover().status_code, 429)
        self.payment.assert_called_once()

    def test_change_requires_real_authenticated_session(self):
        self.assertEqual(self.change(headers={}).status_code, 401)
        self.update.assert_not_called()
        with patch.object(self.module, "auth_obtener_usuario", side_effect=ValueError("expired")):
            self.assertEqual(self.change().status_code, 401)
        self.update.assert_not_called()

    def test_change_requires_strong_password_on_server(self):
        for password in (None, [], "Short1!", "sinmayuscula123!", "SINMINUSCULA123!", "SinNumeroAbc!", "SinSimbolo123", "Espacios 123Aa!"):
            self.assertEqual(self.change({"password": password}).status_code, 400)
        self.update.assert_not_called()

    def test_change_uses_session_owner_never_client_email_or_user_id(self):
        result = self.change({"password": "ClaveNueva123!", "email": "another@example.com", "id": "other-user"})
        self.assertEqual(result.status_code, 200)
        args = self.update.call_args
        self.assertTrue(args.args[0].endswith("/auth/v1/user"))
        self.assertEqual(args.kwargs["headers"]["Authorization"], "Bearer test")
        self.assertEqual(args.kwargs["json"], {"password": "ClaveNueva123!"})
        self.assertEqual(result.json["usuario"], self.user)
        self.assertNotIn("ClaveNueva", str(result.json))

    def test_blocked_session_cannot_change_password(self):
        for _ in range(5):
            self.module.identity_security.record_failure({"correo": self.user["email"]})
        self.assertEqual(self.change().status_code, 403)
        self.update.assert_not_called()

    def test_expired_token_rejected_by_provider_is_not_success(self):
        self.update.return_value.status_code = 401
        self.update.return_value.json.return_value = {"code": "bad_jwt", "message": "private details"}
        result = self.change()
        self.assertEqual(result.status_code, 401)
        self.assertNotIn("private", str(result.json))

    def test_same_password_has_actionable_message(self):
        self.update.return_value.status_code = 422
        self.update.return_value.json.return_value = {"code": "same_password"}
        result = self.change()
        self.assertEqual(result.status_code, 400)
        self.assertIn("diferente", result.json["error"])

    def test_login_invalid_credentials_are_spanish_and_do_not_enumerate_accounts(self):
        self.payment.return_value.status_code = 400
        self.payment.return_value.json.return_value = {"code": "invalid_credentials", "msg": "Invalid login credentials"}
        result = self.client.post("/api/auth/login", json={"email": "buyer@example.com", "password": "incorrecta"})
        self.assertEqual(result.status_code, 401)
        self.assertIn("Olvidé mi contraseña", result.json["error"])
        self.assertNotIn("Invalid login", str(result.json))

    def test_login_accepts_existing_password_without_applying_new_password_policy(self):
        self.payment.return_value.json.return_value = {"access_token": "valid-session", "user": self.user}
        for password in ("old123", "a" * 129):
            result = self.client.post("/api/auth/login", json={"email": "test@example.invalid", "password": password})
            self.assertEqual(result.status_code, 200)
            self.assertEqual(self.payment.call_args.kwargs["json"]["password"], password)

    def test_login_translates_confirmation_and_provider_failures(self):
        for status, body, expected in ((400, {"code": "email_not_confirmed"}, 403), (429, {}, 429), (500, {"msg": "private"}, 502)):
            self.payment.return_value.status_code = status
            self.payment.return_value.json.return_value = body
            result = self.client.post("/api/auth/login", json={"email": "test@example.invalid", "password": "incorrecta"})
            self.assertEqual(result.status_code, expected)
            self.assertFalse(result.json["ok"])
            self.assertNotIn("private", str(result.json))

    def test_login_malformed_input_never_contacts_provider(self):
        for body in (["email"], {"email": []}, {"email": "buyer@example.com", "password": []}):
            self.assertEqual(self.client.post("/api/auth/login", json=body).status_code, 400)
        self.payment.assert_not_called()
