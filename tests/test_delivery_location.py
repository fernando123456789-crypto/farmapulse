import unittest
from unittest.mock import Mock, patch

from delivery_location import _inside_ring, district_for_point
from test_identity_security import CheckoutIdentityFixture


class DeliveryGeometryTests(unittest.TestCase):
    def test_known_points_and_outside_area(self):
        for point, district in (
            ((-12.107, -76.999), "San Borja"), ((-12.074, -76.999), "San Luis"),
            ((-12.073, -77.019), "La Victoria"), ((-12.12, -77.03), None),
        ):
            self.assertEqual(district_for_point(*point), district)

    def test_invalid_coordinates(self):
        for value in (None, True, float("nan"), float("inf"), "-12.1", 999):
            self.assertIsNone(district_for_point(value, -77))

    def test_polygon_ring(self):
        square = [[0, 0], [2, 0], [2, 2], [0, 2], [0, 0]]
        self.assertTrue(_inside_ring(1, 1, square))
        self.assertFalse(_inside_ring(3, 1, square))


class DeliveryEndpointTests(CheckoutIdentityFixture, unittest.TestCase):
    def test_only_the_three_districts_are_accepted(self):
        for latitude, longitude, district in (
            (-12.107, -76.999, "San Borja"), (-12.074, -76.999, "San Luis"),
            (-12.073, -77.019, "La Victoria"),
        ):
            response = self.client.post("/api/direcciones/validar", json={
                "direccion": "Calle de prueba 123", "latitud": latitude, "longitud": longitude,
            }, headers=self.headers)
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json["distrito"], district)
        for latitude, longitude in ((-12.12, -77.03), (-12.093, -77.036), (-16.4, -71.54), (40.71, -74)):
            response = self.client.post("/api/direcciones/validar", json={
                "direccion": "Calle de prueba 123", "latitud": latitude, "longitud": longitude,
                "distrito": "San Borja",
            }, headers=self.headers)
            self.assertEqual(response.status_code, 400)
            self.assertNotIn("validacion", response.json)

    def test_outside_location_cannot_be_used_to_create_or_charge_order(self):
        forged_location = {
            "place_id": self.body["place_id"], "direccion": self.body["direccion"],
            "distrito": "San Borja", "latitud": -12.12, "longitud": -77.03,
        }
        payload = {**self.body, "direccion_validacion": self.module._VALIDACION_DIRECCION.dumps(forged_location)}
        for endpoint in ("orden", "pagar"):
            response = self.client.post(f"/api/checkout/{endpoint}", json=payload, headers=self.headers)
            self.assertEqual(response.status_code, 400)
        self.payment.assert_not_called()
        self.lookup.assert_not_called()

    def test_suggestion_search_rejects_unserved_district_before_contacting_provider(self):
        with patch.object(self.module.requests, "get") as provider:
            response = self.client.post("/api/direcciones/sugerencias", json={
                "texto": "Calle de prueba", "distrito": "Miraflores",
            }, headers=self.headers)
        self.assertEqual(response.status_code, 400)
        provider.assert_not_called()

    def test_point_in_small_street_can_be_selected_without_geocoder(self):
        response = self.client.post("/api/direcciones/validar", json={
            "direccion": "Pasaje de prueba 123, puerta azul", "latitud": -12.107, "longitud": -76.999,
        }, headers=self.headers)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json["distrito"], "San Borja")
        body = {**self.body, "direccion": response.json["direccion"], "place_id": response.json["place_id"],
                "direccion_validacion": response.json["validacion"]}
        customer = self.module._datos_cliente_checkout(body)
        self.assertEqual(customer["latitud"], -12.107)
        self.assertEqual(customer["longitud"], -76.999)
        self.payment.assert_not_called()
        with self.assertRaises(ValueError):
            self.module._datos_cliente_checkout({**body, "direccion": "Otra calle 456"})
        with self.assertRaises(ValueError):
            self.module._datos_cliente_checkout({**body, "distrito": "San Luis"})

    def test_outside_point_rejected_despite_claimed_district(self):
        response = self.client.post("/api/direcciones/validar", json={
            "direccion": "Direccion de prueba 123", "latitud": -12.12, "longitud": -77.03,
            "distrito": "San Borja",
        }, headers=self.headers)
        self.assertEqual(response.status_code, 400)
        self.assertNotIn("validacion", response.json)

    def test_suggestions_exclude_large_places_and_wrong_house_numbers(self):
        def feature(kind, name, street="", number="", lat=-12.107, lon=-76.999):
            return {"geometry": {"coordinates": [lon, lat]}, "properties": {
                "type": kind, "name": name, "street": street, "housenumber": number,
            }}
        response = Mock()
        response.json.return_value = {"features": [
            feature("city", "San Borja"), feature("house", "", "Las Artes", "999"),
            feature("street", "Las Artes"), feature("house", "", "Las Artes", "123"),
            feature("house", "", "Otra Calle", "123"),
            feature("house", "", "Las Artes", "123", lat=-12.12, lon=-77.03),
        ]}
        with patch.object(self.module.requests, "get", return_value=response):
            results = self.module._consultar_sugerencias_direccion("Calle Las Artes 123", "San Borja")
        self.assertEqual(len(results), 2)
        self.assertTrue(results[0]["direccion_precisa"])
        self.assertIn("123", results[0]["descripcion"])
        self.assertFalse(results[1]["direccion_precisa"])
