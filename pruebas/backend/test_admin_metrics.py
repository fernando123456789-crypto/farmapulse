"""Reglas del panel con órdenes ficticias; no abre la base de pagos."""

from copy import deepcopy
from datetime import date

from admin_panel import ParametrosInvalidos, construir_panel, leer_parametros, rango_utc
from pruebas.backend.support import OfflineUnitTestCase


def order(order_id="unit-order", status="approved", total="15.00", quantity=1,
          created_at="2026-10-23 15:00:00", product="Paracetamol"):
    return {
        "id": order_id, "estado": status, "created_at": created_at,
        "cliente": "Persona de Prueba", "email": "buyer@example.invalid",
        "subtotal": total, "delivery": "0.00", "total": total, "legible": True,
        "productos": [{
            "nombre": product, "presentacion": "Caja de prueba",
            "farmacia": "Farmacia de prueba", "cantidad": quantity,
        }],
    }


class AdminParameterTests(OfflineUnitTestCase):
    def test_defaults_are_valid_and_bounded(self):
        parameters = leer_parametros({})

        self.assertEqual(parameters["pagina"], 1)
        self.assertEqual(parameters["por_pagina"], 25)
        self.assertEqual(parameters["orden"], "fecha_desc")
        self.assertIsNone(parameters["desde"])

    def test_rejects_date_with_non_iso_format(self):
        parameters = {"desde": "23/10/2026"}

        with self.assertRaises(ParametrosInvalidos):
            leer_parametros(parameters)

    def test_rejects_nonexistent_calendar_date(self):
        parameters = {"hasta": "2026-02-30"}

        with self.assertRaises(ParametrosInvalidos):
            leer_parametros(parameters)

    def test_rejects_reversed_date_range(self):
        parameters = {"desde": "2026-10-24", "hasta": "2026-10-23"}

        with self.assertRaises(ParametrosInvalidos):
            leer_parametros(parameters)

    def test_rejects_unknown_payment_state(self):
        parameters = {"estado": "inventado"}

        with self.assertRaises(ParametrosInvalidos):
            leer_parametros(parameters)

    def test_rejects_unknown_sort_order(self):
        parameters = {"orden": "campo_inexistente"}

        with self.assertRaises(ParametrosInvalidos):
            leer_parametros(parameters)

    def test_rejects_non_numeric_page(self):
        parameters = {"pagina": "abc"}

        with self.assertRaises(ParametrosInvalidos):
            leer_parametros(parameters)

    def test_bounds_page_size_and_normalizes_search(self):
        parameters = leer_parametros({
            "pagina": "-3", "por_pagina": "1000", "q": "  PARACETAMOL   Caja  ",
        })

        self.assertEqual(parameters["pagina"], 1)
        self.assertEqual(parameters["por_pagina"], 100)
        self.assertEqual(parameters["q"], "paracetamol caja")

    def test_lima_date_range_becomes_utc_with_exclusive_upper_bound(self):
        start, end = rango_utc(date(2026, 10, 23), date(2026, 10, 23))

        self.assertEqual(start, "2026-10-23 05:00:00")
        self.assertEqual(end, "2026-10-24 05:00:00")


class AdminMetricsTests(OfflineUnitTestCase):
    def test_empty_panel_has_zero_revenue_and_one_empty_page(self):
        panel = construir_panel([], leer_parametros({}))

        self.assertEqual(panel["resumen"]["ingresos"], "0.00")
        self.assertEqual(panel["resumen"]["ticket_promedio"], "0.00")
        self.assertEqual(panel["compras"], [])
        self.assertEqual(panel["paginacion"]["paginas"], 1)

    def test_only_approved_orders_contribute_to_revenue(self):
        # Arrange: los estados no aprobados tienen importes altos para detectar sumas indebidas.
        orders = [order("approved-1", total="10.10"), order("approved-2", total="20.20")]
        orders.extend(order(status, status=status, total="999.99") for status in (
            "pending", "processing", "unknown", "rejected",
        ))

        # Act: construyo el resumen desde datos en memoria.
        panel = construir_panel(orders, leer_parametros({}))

        # Assert: los importes exactos provienen solo de compras aprobadas.
        self.assertEqual(panel["resumen"]["ingresos"], "30.30")
        self.assertEqual(panel["resumen"]["ticket_promedio"], "15.15")
        self.assertEqual(panel["resumen"]["compras_aprobadas"], 2)
        self.assertEqual(panel["resumen"]["registros"], 6)

    def test_only_approved_product_units_are_counted(self):
        orders = [order("approved", quantity=3), order("pending", status="pending", quantity=100)]

        panel = construir_panel(orders, leer_parametros({}))

        self.assertEqual(panel["resumen"]["unidades"], 3)
        self.assertEqual(panel["top_productos"], [{"nombre": "Paracetamol", "unidades": 3}])

    def test_invalid_money_never_inflates_or_breaks_metrics(self):
        for value in ("NaN", "Infinity", "no-es-un-importe", "-5"):
            with self.subTest(value=value):
                panel = construir_panel([order(total=value)], leer_parametros({}))

                self.assertEqual(panel["resumen"]["ingresos"], "0.00")

    def test_search_and_state_filters_apply_before_summary(self):
        orders = [
            order("match", product="Paracetamol", total="10.00"),
            order("different-product", product="Ibuprofeno", total="50.00"),
            order("not-approved", status="pending", product="Paracetamol"),
        ]

        panel = construir_panel(orders, leer_parametros({"q": "PARACETAMOL", "estado": "approved"}))

        self.assertEqual([row["id"] for row in panel["compras"]], ["match"])
        self.assertEqual(panel["resumen"]["ingresos"], "10.00")

    def test_pagination_does_not_reduce_total_revenue(self):
        orders = [order(str(index), total="10.00") for index in range(3)]

        panel = construir_panel(orders, leer_parametros({"por_pagina": "1", "pagina": "2"}))

        self.assertEqual(len(panel["compras"]), 1)
        self.assertEqual(panel["resumen"]["ingresos"], "30.00")
        self.assertEqual(panel["paginacion"], {"pagina": 2, "paginas": 3, "por_pagina": 1, "total": 3})

    def test_amount_sort_uses_numbers_instead_of_lexicographic_order(self):
        orders = [order("large", total="100.00"), order("small", total="9.00")]

        panel = construir_panel(orders, leer_parametros({"orden": "importe_asc"}))

        self.assertEqual([row["id"] for row in panel["compras"]], ["small", "large"])

    def test_daily_series_uses_lima_timezone_and_fills_missing_days(self):
        orders = [
            order("first", created_at="2026-10-23 02:00:00", total="10.00"),
            order("last", created_at="2026-10-24 15:00:00", total="20.00"),
        ]

        panel = construir_panel(orders, leer_parametros({}))

        self.assertEqual(panel["serie"], [
            {"dia": "2026-10-22", "compras": 1, "ingresos": "10.00"},
            {"dia": "2026-10-23", "compras": 0, "ingresos": "0.00"},
            {"dia": "2026-10-24", "compras": 1, "ingresos": "20.00"},
        ])

    def test_report_does_not_mutate_input_orders(self):
        orders = [order()]
        original = deepcopy(orders)

        construir_panel(orders, leer_parametros({}))

        self.assertEqual(orders, original)
