"""Verifica órdenes y estados con respuestas ficticias; nunca llama a Mercado Pago."""

import json
from copy import deepcopy
from decimal import Decimal

from mercado_pago import crear_orden, leer_orden
from pruebas.backend.support import OfflineUnitTestCase


REFERENCE = "fp-unit-order"
TOTAL = Decimal("15.00")


def approved_order():
    """Cada caso recibe su propia orden para evitar contaminación entre pruebas."""
    return {
        "id": "ORD" + "A" * 26,
        "type": "online",
        "external_reference": REFERENCE,
        "currency": "PEN",
        "total_amount": "15.00",
        "total_paid_amount": "15.00",
        "status": "processed",
        "status_detail": "accredited",
        "transactions": {"payments": [{
            "id": "PAY" + "B" * 26,
            "amount": "15.00",
            "paid_amount": "15.00",
            "status": "processed",
            "status_detail": "accredited",
            "payment_method": {"id": "visa", "type": "credit_card"},
        }]},
    }


class OrderCreationTests(OfflineUnitTestCase):
    def setUp(self):
        super().setUp()
        self.customer = {"nombres": "Persona", "apellidos": "De Prueba", "dni": "00000000"}

    def create(self, total=TOTAL):
        return crear_orden(
            REFERENCE, total, "buyer@example.invalid", self.customer,
            "test-token", "visa", "credit_card", 1,
        )

    def test_formats_money_as_two_decimal_places(self):
        order = self.create(Decimal("15"))

        self.assertEqual(order["total_amount"], "15.00")
        self.assertEqual(order["transactions"]["payments"][0]["amount"], "15.00")

    def test_preserves_reference_and_customer_identity(self):
        order = self.create()

        self.assertEqual(order["external_reference"], REFERENCE)
        self.assertEqual(order["payer"], {
            "email": "buyer@example.invalid", "first_name": "Persona", "last_name": "De Prueba",
            "identification": {"type": "DNI", "number": "00000000"},
        })

    def test_only_forwards_card_token_and_never_raw_card_fields(self):
        self.customer.update({"numero_tarjeta": "DATO_PROHIBIDO", "cvv": "NO_GUARDAR"})

        order = self.create()

        method = order["transactions"]["payments"][0]["payment_method"]
        self.assertEqual(method["token"], "test-token")
        self.assertNotIn("DATO_PROHIBIDO", json.dumps(order))
        self.assertNotIn("NO_GUARDAR", json.dumps(order))

    def test_does_not_mutate_customer_input(self):
        original = deepcopy(self.customer)

        self.create()

        self.assertEqual(self.customer, original)


class OrderVerificationTests(OfflineUnitTestCase):
    def test_approves_only_a_fully_accredited_order(self):
        # Arrange: el proveedor confirma referencia, moneda e importe completos.
        order = approved_order()

        # Act: verifico el contenido, no solo el estado HTTP del proveedor.
        result = leer_orden(order, REFERENCE, TOTAL)

        # Assert: la regla de negocio reconoce la acreditación.
        self.assertEqual(result["estado"], "approved")
        self.assertEqual(result["pago_id"], order["transactions"]["payments"][0]["id"])

    def test_rejects_order_with_wrong_identity_currency_or_amount(self):
        for field, value in (
            ("id", "invalid-id"), ("type", "offline"),
            ("external_reference", "another-order"), ("currency", "USD"),
            ("total_amount", "14.99"),
        ):
            with self.subTest(field=field):
                order = approved_order()
                order[field] = value

                with self.assertRaisesRegex(ValueError, "Orden no verificable"):
                    leer_orden(order, REFERENCE, TOTAL)

    def test_requires_exactly_one_payment(self):
        for count in (0, 2):
            with self.subTest(count=count):
                order = approved_order()
                payment = order["transactions"]["payments"][0]
                order["transactions"]["payments"] = [deepcopy(payment) for _ in range(count)]

                with self.assertRaises(ValueError):
                    leer_orden(order, REFERENCE, TOTAL)

    def test_rejects_invalid_payment_id_amount_or_type(self):
        for change in ("id", "amount", "type"):
            with self.subTest(change=change):
                order = approved_order()
                payment = order["transactions"]["payments"][0]
                if change == "type":
                    payment["payment_method"]["type"] = "account_money"
                else:
                    payment[change] = "invalid" if change == "id" else "10.00"

                with self.assertRaisesRegex(ValueError, "Transacción no verificable"):
                    leer_orden(order, REFERENCE, TOTAL)

    def test_rejects_approval_if_paid_total_is_incomplete(self):
        for level in ("order", "payment"):
            with self.subTest(level=level):
                order = approved_order()
                if level == "order":
                    order["total_paid_amount"] = "14.00"
                else:
                    order["transactions"]["payments"][0]["paid_amount"] = "14.00"

                with self.assertRaisesRegex(ValueError, "acreditado"):
                    leer_orden(order, REFERENCE, TOTAL)

    def test_processing_states_remain_pending(self):
        for status in ("created", "processing", "action_required"):
            with self.subTest(status=status):
                order = approved_order()
                order.update(status=status, status_detail="pending")

                result = leer_orden(order, REFERENCE, TOTAL)

                self.assertEqual(result["estado"], "pending")

    def test_failed_and_reversed_orders_are_rejected(self):
        for status in ("failed", "canceled", "cancelled", "expired", "refunded", "charged_back"):
            with self.subTest(status=status):
                order = approved_order()
                order["status"] = status

                result = leer_orden(order, REFERENCE, TOTAL)

                self.assertEqual(result["estado"], "rejected")

    def test_unrecognized_state_is_never_treated_as_approved(self):
        order = approved_order()
        order["status"] = "future-provider-state"

        result = leer_orden(order, REFERENCE, TOTAL)

        self.assertEqual(result["estado"], "unknown")

    def test_security_challenge_only_accepts_trusted_https_urls(self):
        for url, allowed in (
            ("https://www.mercadopago.com.pe/challenge", True),
            ("http://www.mercadopago.com.pe/challenge", False),
            ("https://www.mercadopago.com.pe.attacker.invalid/challenge", False),
            ("https://attacker.invalid/challenge", False),
            ("https://user:password@www.mercadopago.com.pe/challenge", False),
            ("https://www.mercadopago.com.pe:8443/challenge", False),
        ):
            with self.subTest(url=url):
                order = approved_order()
                order.update(status="action_required", status_detail="pending_challenge")
                method = order["transactions"]["payments"][0]["payment_method"]
                method["transaction_security"] = {"url": url}

                result = leer_orden(order, REFERENCE, TOTAL)

                self.assertEqual("challenge_url" in result, allowed)
                self.assertEqual(result["estado"], "pending")

    def test_verification_does_not_mutate_provider_response(self):
        order = approved_order()
        original = deepcopy(order)

        leer_orden(order, REFERENCE, TOTAL)

        self.assertEqual(order, original)
