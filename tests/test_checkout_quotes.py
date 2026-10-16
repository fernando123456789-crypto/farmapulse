import unittest
from decimal import Decimal
from unittest.mock import patch

from test_identity_security import CheckoutIdentityFixture


class CheckoutQuoteTests(CheckoutIdentityFixture, unittest.TestCase):
    def setUp(self):
        super().setUp()
        self.product = {"medicamento": "Paracetamol 500 mg", "farmacia": "Inkafarma",
                        "presentacion": "Caja de 10", "precio_empaque": 12.50,
                        "precio_unitario": 1.25, "tipo": "GENERICO"}
        self.catalog = self.patch(patch.object(self.module, "buscar_en_farmacias", return_value=[self.product]))

    def quote(self, items):
        return self.client.post("/api/checkout/cotizar", json={"productos": items}, headers=self.headers)

    def test_old_cart_recovers_signed_price_and_ignores_browser_amount(self):
        response = self.quote([{**self.product, "precio_empaque": 0.01}])
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json["subtotal"], "12.50")
        item = response.json["productos"][0]
        self.assertEqual(item["precio_empaque"], 12.50)
        self.assertEqual(self.module._COTIZACIONES.loads(item["cotizacion"])["precio"], "12.50")
        self.payment.assert_not_called()

    def test_current_quote_keeps_server_amount_without_another_search(self):
        item = self.module._firmar_precio_producto(self.product)
        response = self.quote([{**item, "precio_empaque": 0.01}])
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json["productos"][0]["precio_empaque"], 12.50)
        self.catalog.assert_not_called()

    def test_expired_quote_refreshes_from_catalog(self):
        with patch("itsdangerous.timed.time.time", return_value=1):
            item = self.module._firmar_precio_producto({**self.product, "precio_empaque": 9})
        response = self.quote([item])
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json["subtotal"], "12.50")
        self.catalog.assert_called_once()

    def test_missing_presentation_is_not_silently_replaced(self):
        response = self.quote([{**self.product, "presentacion": "Caja de 100"}])
        self.assertEqual(response.status_code, 409)
        self.assertNotIn("productos", response.json)
        self.payment.assert_not_called()

    def test_unavailable_product_never_gets_a_quote(self):
        self.catalog.return_value = []
        self.assertEqual(self.quote([self.product]).status_code, 409)
        self.payment.assert_not_called()

    def test_ambiguous_offers_do_not_choose_arbitrary_price(self):
        self.catalog.return_value = [self.product, {**self.product, "precio_empaque": 25}]
        self.assertEqual(self.quote([self.product]).status_code, 409)

    def test_malformed_cart_is_rejected_before_searching(self):
        for items in (None, [], [None], [{"medicamento": []}], [self.product] * 21,
                      [{**self.product, "presentacion": []}]):
            self.assertEqual(self.quote(items).status_code, 400)
        self.catalog.assert_not_called()

    def test_real_search_results_are_purchasable_and_signed(self):
        response = self.client.post("/api/buscar", json={"producto": "paracetamol"}, headers=self.headers)
        item = response.json["resultados"][0]
        self.assertTrue(item["comprable"])
        self.assertEqual(Decimal(self.module._COTIZACIONES.loads(item["cotizacion"])["precio"]), Decimal("12.50"))

    def test_demo_results_cannot_be_purchased(self):
        self.catalog.return_value = []
        response = self.client.post("/api/buscar", json={"producto": "paracetamol"}, headers=self.headers)
        self.assertEqual(response.json["fuente"], "demo")
        self.assertTrue(response.json["resultados"])
        for item in response.json["resultados"]:
            self.assertFalse(item["comprable"])
            self.assertNotIn("cotizacion", item)
