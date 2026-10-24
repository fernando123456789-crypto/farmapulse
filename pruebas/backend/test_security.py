"""Contratos de validación y mensajes seguros, con datos completamente ficticios."""

from security import (
    enmascarar_error_auth,
    sanitizar_termino_busqueda,
    validar_contrasena,
    validar_email,
)
from pruebas.backend.support import OfflineUnitTestCase


class PasswordValidationTests(OfflineUnitTestCase):
    def test_accepts_password_at_minimum_length(self):
        password = "Aa1!" + "b" * 8

        valid, message = validar_contrasena(password)

        self.assertTrue(valid)
        self.assertEqual(message, "OK")

    def test_accepts_password_at_maximum_length(self):
        password = "Aa1!" + "b" * 124

        valid, _ = validar_contrasena(password)

        self.assertTrue(valid)

    def test_rejects_password_outside_length_bounds(self):
        for length in (0, 11, 129):
            with self.subTest(length=length):
                password = ("Aa1!" + "b" * length)[:length]

                valid, message = validar_contrasena(password)

                self.assertFalse(valid)
                self.assertIn("caracteres", message)

    def test_rejects_non_text_passwords_without_raising(self):
        for value in (None, 123456789012, True, [], {}):
            with self.subTest(value=value):
                valid, message = validar_contrasena(value)

                self.assertFalse(valid)
                self.assertIn("texto", message)

    def test_rejects_password_without_uppercase(self):
        valid, message = validar_contrasena("abcdefghi12!")

        self.assertFalse(valid)
        self.assertIn("mayúscula", message)

    def test_rejects_password_without_lowercase(self):
        valid, message = validar_contrasena("ABCDEFGHI12!")

        self.assertFalse(valid)
        self.assertIn("minúscula", message)

    def test_rejects_password_without_number(self):
        valid, message = validar_contrasena("Abcdefghijk!")

        self.assertFalse(valid)
        self.assertIn("número", message)

    def test_rejects_password_without_special_character(self):
        valid, message = validar_contrasena("Abcdefghij12")

        self.assertFalse(valid)
        self.assertIn("especial", message)

    def test_rejects_spaces_tabs_and_line_feeds(self):
        for separator in (" ", "\t", "\n"):
            with self.subTest(separator=repr(separator)):
                password = "ClaveSegura123!" + separator

                valid, message = validar_contrasena(password)

                self.assertFalse(valid)
                self.assertIn("espacios", message)


class EmailValidationTests(OfflineUnitTestCase):
    def test_accepts_valid_email_alias_and_surrounding_spaces(self):
        valid, message = validar_email("  Comprador+prueba@Example.invalid  ")

        self.assertTrue(valid)
        self.assertEqual(message, "OK")

    def test_rejects_missing_email(self):
        for email in (None, ""):
            with self.subTest(email=email):
                valid, message = validar_email(email)

                self.assertFalse(valid)
                self.assertIn("requerido", message)

    def test_rejects_malformed_email(self):
        for email in ("usuario", "usuario@", "@example.invalid", "a@@example.invalid", "a b@example.invalid"):
            with self.subTest(email=email):
                valid, message = validar_email(email)

                self.assertFalse(valid)
                self.assertIn("inválido", message)

    def test_accepts_email_at_total_length_limit(self):
        email = "a" * 64 + "@" + "b" * 63 + "." + "c" * 63 + "." + "d" * 58 + ".co"
        self.assertEqual(len(email), 254)

        valid, _ = validar_email(email)

        self.assertTrue(valid)

    def test_rejects_email_over_total_length_limit(self):
        email = "a" * 64 + "@" + "b" * 63 + "." + "c" * 63 + "." + "d" * 59 + ".co"

        valid, message = validar_email(email)

        self.assertFalse(valid)
        self.assertIn("largo", message)


class SearchValidationTests(OfflineUnitTestCase):
    def test_normalizes_whitespace_without_changing_product_name(self):
        term = "  Ácido   acetilsalicílico\t100 mg  "

        valid, message, cleaned = sanitizar_termino_busqueda(term)

        self.assertTrue(valid)
        self.assertEqual(message, "OK")
        self.assertEqual(cleaned, "Ácido acetilsalicílico 100 mg")

    def test_rejects_empty_or_too_short_terms(self):
        for term in (None, "", "  ", "a"):
            with self.subTest(term=term):
                valid, message, cleaned = sanitizar_termino_busqueda(term)

                self.assertFalse(valid)
                self.assertTrue(message)
                self.assertEqual(cleaned, "")

    def test_enforces_search_length_boundaries(self):
        for length, expected in ((2, True), (100, True), (101, False)):
            with self.subTest(length=length):
                valid, _, _ = sanitizar_termino_busqueda("a" * length)

                self.assertEqual(valid, expected)

    def test_honors_explicit_search_length_limit(self):
        valid, _, cleaned = sanitizar_termino_busqueda("paracetamol", max_chars=5)

        self.assertFalse(valid)
        self.assertEqual(cleaned, "")

    def test_rejects_html_and_script_delimiters(self):
        for term in ("<script>alert(1)</script>", "<img src=x>", "producto`", 'producto"'):
            with self.subTest(term=term):
                valid, _, cleaned = sanitizar_termino_busqueda(term)

                self.assertFalse(valid)
                self.assertEqual(cleaned, "")


class AuthenticationErrorTests(OfflineUnitTestCase):
    def test_account_existence_errors_have_same_public_message(self):
        errors = ("User already registered", "USER NOT FOUND", "invalid login credentials", "invalid password")

        messages = [enmascarar_error_auth(error) for error in errors]

        self.assertEqual(messages, ["Credenciales inválidas"] * len(errors))

    def test_unknown_error_does_not_expose_provider_details(self):
        internal_error = "Internal provider failure: token=secret-test-value"

        message = enmascarar_error_auth(internal_error)

        self.assertEqual(message, "Ocurrió un error. Intenta más tarde o contacta al soporte.")
        self.assertNotIn("secret-test-value", message)

    def test_confirmation_and_rate_limit_errors_are_actionable(self):
        for error, expected in (
            ("email_not_confirmed", "confirma"),
            ("too many requests", "Demasiados intentos"),
        ):
            with self.subTest(error=error):
                message = enmascarar_error_auth(error)

                self.assertIn(expected, message)
