import unittest

from werkzeug.test import Client
from werkzeug.wrappers import Response

from local_https import redirect_to_https


class LocalHttpsTests(unittest.TestCase):
    def setUp(self):
        self.client = Client(redirect_to_https(5443), Response)

    def test_http_navigation_moves_to_fixed_https_origin(self):
        result = self.client.get("/comparador?opcion=carrito", headers={"Host": "attacker.invalid"})
        self.assertEqual(result.status_code, 307)
        self.assertEqual(result.headers["Location"], "https://127.0.0.1:5443/comparador?opcion=carrito")
        self.assertEqual(result.headers["Cache-Control"], "no-store")

    def test_insecure_posts_are_not_forwarded(self):
        result = self.client.post("/api/checkout/pagar", json={"token": "not-a-real-token"})
        self.assertEqual(result.status_code, 426)
        self.assertNotIn("Location", result.headers)
