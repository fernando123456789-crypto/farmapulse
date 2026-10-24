"""Caché y selección de farmacias con reloj controlado y consultas simuladas."""

from datetime import datetime, timezone
from unittest.mock import create_autospec, patch

from scrapers.base import ScraperFarmacia
from scrapers import registry
from pruebas.backend.support import OfflineUnitTestCase


class StubPharmacy(ScraperFarmacia):
    nombre_farmacia = "Farmacia de prueba"

    def _buscar_en_vivo(self, termino):
        raise AssertionError("La consulta de la farmacia debe estar simulada")


class PharmacySearchTests(OfflineUnitTestCase):
    def setUp(self):
        super().setUp()
        self.scraper = StubPharmacy()
        self.product = {"medicamento": "Paracetamol", "precio_unitario": 1.25}
        self.source = self.enterContext(patch.object(
            self.scraper, "_buscar_en_vivo", autospec=True, return_value=[self.product],
        ))
        self.clock = self.enterContext(patch("scrapers.base.time.time", return_value=10_000.0))
        clock = self.enterContext(patch("scrapers.base.datetime", wraps=datetime))
        clock.now.return_value = datetime(2026, 10, 23, 12, tzinfo=timezone.utc)

    def test_empty_search_never_contacts_source(self):
        for term in (None, "", "   "):
            with self.subTest(term=term):
                result = self.scraper.buscar(term)

                self.assertEqual(result, [])
        self.source.assert_not_called()

    def test_adds_metadata_and_preserves_existing_product_fields(self):
        result = self.scraper.buscar("  paracetamol  ")

        self.assertEqual(result[0]["medicamento"], "Paracetamol")
        self.assertEqual(result[0]["precio_unitario"], 1.25)
        self.assertEqual(result[0]["farmacia"], "Farmacia de prueba")
        self.assertEqual(result[0]["consultado_en"], "2026-10-23T12:00:00+00:00")
        self.source.assert_called_once_with("paracetamol")

    def test_repeated_search_uses_cache_instead_of_another_request(self):
        # Arrange: una primera consulta llena la caché con una respuesta simulada.
        first = self.scraper.buscar("paracetamol")
        self.clock.return_value += 1

        # Act: consulto el mismo término dentro de su vigencia.
        repeated = self.scraper.buscar("paracetamol")

        # Assert: obtengo los datos sin volver a consultar a la farmacia.
        self.assertEqual(repeated, first)
        self.source.assert_called_once()

    def test_expired_cache_refreshes_source(self):
        self.scraper.buscar("paracetamol")
        self.clock.return_value += 901
        self.source.return_value = [{"medicamento": "Paracetamol", "precio_unitario": 2.50}]

        result = self.scraper.buscar("paracetamol")

        self.assertEqual(result[0]["precio_unitario"], 2.50)
        self.assertEqual(self.source.call_count, 2)

    def test_minimum_interval_prevents_a_second_live_query(self):
        self.scraper.buscar("paracetamol")
        self.clock.return_value += 1

        result = self.scraper.buscar("ibuprofeno")

        self.assertEqual(result, [])
        self.source.assert_called_once()

    def test_expired_data_can_be_reused_during_minimum_interval(self):
        first = self.scraper.buscar("paracetamol")
        self.clock.return_value += 901
        self.scraper.buscar("ibuprofeno")
        self.clock.return_value += 1

        result = self.scraper.buscar("paracetamol")

        self.assertEqual(result, first)
        self.assertEqual(self.source.call_count, 2)

    def test_source_failure_returns_empty_results(self):
        self.source.side_effect = TimeoutError("Proveedor ficticio no disponible")
        with patch("builtins.print"):
            result = self.scraper.buscar("paracetamol")

        self.assertEqual(result, [])
        self.source.assert_called_once()

    def test_cache_is_not_shared_between_pharmacy_instances(self):
        self.scraper.buscar("paracetamol")
        other = StubPharmacy()
        with patch.object(other, "_buscar_en_vivo", autospec=True, return_value=[]) as source:
            result = other.buscar("paracetamol")

        self.assertEqual(result, [])
        source.assert_called_once_with("paracetamol")


class PharmacyRegistryTests(OfflineUnitTestCase):
    def setUp(self):
        super().setUp()
        self.first = create_autospec(ScraperFarmacia, instance=True, spec_set=True)
        self.first.nombre_farmacia = "Farmacia Norte"
        self.first.buscar.return_value = [{"medicamento": "Producto Norte"}]
        self.second = create_autospec(ScraperFarmacia, instance=True, spec_set=True)
        self.second.nombre_farmacia = "Farmacia Sur"
        self.second.buscar.return_value = [{"medicamento": "Producto Sur"}]
        self.enterContext(patch.object(registry, "SCRAPERS_ACTIVOS", [self.first, self.second]))

    def test_combines_results_from_active_pharmacies(self):
        result = registry.buscar_en_farmacias("paracetamol")

        self.assertEqual(result, [{"medicamento": "Producto Norte"}, {"medicamento": "Producto Sur"}])
        self.first.buscar.assert_called_once_with("paracetamol")
        self.second.buscar.assert_called_once_with("paracetamol")

    def test_pharmacy_filter_ignores_case_and_surrounding_spaces(self):
        result = registry.buscar_en_farmacias("paracetamol", farmacia_filtro="  SUR  ")

        self.assertEqual(result, [{"medicamento": "Producto Sur"}])
        self.first.buscar.assert_not_called()
        self.second.buscar.assert_called_once_with("paracetamol")

    def test_unavailable_pharmacy_does_not_remove_other_results(self):
        self.first.buscar.return_value = []

        result = registry.buscar_en_farmacias("paracetamol")

        self.assertEqual(result, [{"medicamento": "Producto Sur"}])
        self.second.buscar.assert_called_once()

    def test_unknown_filter_never_queries_any_pharmacy(self):
        result = registry.buscar_en_farmacias("paracetamol", farmacia_filtro="inexistente")

        self.assertEqual(result, [])
        self.first.buscar.assert_not_called()
        self.second.buscar.assert_not_called()
