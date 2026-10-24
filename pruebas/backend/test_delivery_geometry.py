"""Cobertura geográfica con polígonos sintéticos, sin mapas ni geocodificador."""

import json
from unittest.mock import patch

import delivery_location
from pruebas.backend.support import OfflineUnitTestCase


def rectangle(left, bottom, right, top):
    return [[left, bottom], [right, bottom], [right, top], [left, top], [left, bottom]]


def area(rings, district="150130", geometry_type="Polygon"):
    return {
        "properties": {"IDDIST": district},
        "geometry": {"type": geometry_type, "coordinates": rings},
    }


class DeliveryGeometryTests(OfflineUnitTestCase):
    def setUp(self):
        super().setUp()
        self.areas = self.enterContext(patch.object(delivery_location, "delivery_areas", autospec=True))
        self.areas.return_value = [area([rectangle(0, 10, 2, 12)])]

    def test_matches_latitude_and_longitude_in_correct_order(self):
        district = delivery_location.district_for_point(latitude=11, longitude=1)

        self.assertEqual(district, "San Borja")

    def test_point_outside_polygon_has_no_delivery(self):
        district = delivery_location.district_for_point(latitude=20, longitude=20)

        self.assertIsNone(district)

    def test_polygon_holes_are_excluded_from_delivery(self):
        self.areas.return_value = [area([
            rectangle(0, 0, 10, 10), rectangle(4, 4, 6, 6),
        ])]

        district = delivery_location.district_for_point(latitude=5, longitude=5)

        self.assertIsNone(district)

    def test_point_outside_hole_but_inside_polygon_is_served(self):
        self.areas.return_value = [area([
            rectangle(0, 0, 10, 10), rectangle(4, 4, 6, 6),
        ])]

        district = delivery_location.district_for_point(latitude=2, longitude=2)

        self.assertEqual(district, "San Borja")

    def test_accepts_point_in_second_part_of_multipolygon(self):
        self.areas.return_value = [area(
            [[rectangle(0, 10, 2, 12)], [rectangle(4, 14, 6, 16)]],
            district="150134", geometry_type="MultiPolygon",
        )]

        district = delivery_location.district_for_point(latitude=15, longitude=5)

        self.assertEqual(district, "San Luis")

    def test_invalid_coordinates_are_rejected_before_loading_areas(self):
        for latitude, longitude in (
            (None, 0), (True, 0), (0, False), ("11", 1),
            (float("nan"), 0), (0, float("inf")),
            (91, 0), (-91, 0), (0, 181), (0, -181),
        ):
            with self.subTest(latitude=latitude, longitude=longitude):
                district = delivery_location.district_for_point(latitude, longitude)

                self.assertIsNone(district)
        self.areas.assert_not_called()

    def test_empty_coverage_returns_no_district(self):
        self.areas.return_value = []

        district = delivery_location.district_for_point(11, 1)

        self.assertIsNone(district)


class DeliveryAreaLoadingTests(OfflineUnitTestCase):
    def setUp(self):
        super().setUp()
        delivery_location.delivery_areas.cache_clear()
        self.addCleanup(delivery_location.delivery_areas.cache_clear)

    def test_only_loads_supported_districts_and_caches_the_result(self):
        features = [area([], district=code) for code in ("150130", "150134", "150115", "unsupported")]
        document = json.dumps({"features": features})
        with patch("delivery_location.Path.read_text", autospec=True, return_value=document) as read:
            first = delivery_location.delivery_areas()
            repeated = delivery_location.delivery_areas()

        self.assertEqual([feature["properties"]["IDDIST"] for feature in first], ["150130", "150134", "150115"])
        self.assertEqual(repeated, first)
        read.assert_called_once()
