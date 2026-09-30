import unittest
from unittest.mock import MagicMock

from dao.captura_precios_dao import CapturaPreciosDAO
from dao.receta_dao import RecetaDAO


class RecetaDAOTests(unittest.TestCase):
    def test_guardar_usa_supabase(self):
        registro = {"id": "receta-1", "usuario_id": "usuario-1"}
        cliente = MagicMock()
        cliente.table.return_value.insert.return_value.execute.return_value.data = [registro]
        dao = RecetaDAO(cliente)

        fuente, datos = dao.guardar(registro)

        self.assertEqual("supabase", fuente)
        self.assertEqual([registro], datos)
        cliente.table.assert_called_once_with("listas_recetas")

    def test_guardar_y_listar_usan_fallback_local(self):
        memoria = []
        dao = RecetaDAO(memoria=memoria)
        registro_usuario = {"id": "receta-1", "usuario_id": "usuario-1"}
        registro_otro_usuario = {"id": "receta-2", "usuario_id": "usuario-2"}

        fuente, datos = dao.guardar(registro_usuario)
        memoria.append(registro_otro_usuario)
        fuente_historial, historial = dao.listar_por_usuario("usuario-1")

        self.assertEqual(("memoria_local", registro_usuario), (fuente, datos))
        self.assertEqual("memoria_local", fuente_historial)
        self.assertEqual([registro_usuario], historial)

    def test_guardar_falla_a_memoria_si_supabase_falla(self):
        registro = {"id": "receta-1", "usuario_id": "usuario-1"}
        cliente = MagicMock()
        cliente.table.return_value.insert.return_value.execute.side_effect = RuntimeError(
            "sin conexión"
        )
        memoria = []
        dao = RecetaDAO(cliente, memoria)

        with self.assertLogs("dao.receta_dao", level="ERROR"):
            fuente, datos = dao.guardar(registro)

        self.assertEqual("memoria_local", fuente)
        self.assertIs(registro, datos)
        self.assertEqual([registro], memoria)


class CapturaPreciosDAOTests(unittest.TestCase):
    def test_id_de_farmacia_se_cachea(self):
        cliente = MagicMock()
        consulta = cliente.table.return_value.select.return_value.eq.return_value.execute
        consulta.return_value.data = [{"id": 12}]
        dao = CapturaPreciosDAO(cliente)

        self.assertEqual(12, dao.obtener_o_crear_farmacia_id("Botica Ejemplo"))
        self.assertEqual(12, dao.obtener_o_crear_farmacia_id("Botica Ejemplo"))

        cliente.table.assert_called_once_with("farmacias")

    def test_presentacion_vacia_no_consulta_base(self):
        cliente = MagicMock()
        dao = CapturaPreciosDAO(cliente)

        self.assertIsNone(dao.obtener_o_crear_presentacion_id("  "))
        cliente.table.assert_not_called()

    def test_insertar_precio_y_log_usa_tablas_correspondientes(self):
        cliente = MagicMock()
        dao = CapturaPreciosDAO(cliente)
        precio = {"medicamento_id": "med-1", "precio_unitario": 1.25}
        log = {"medicamento_id": "med-1", "encontrado": True}

        dao.insertar_precio(precio)
        dao.registrar_scrape(log)

        self.assertEqual(
            [
                unittest.mock.call("precios"),
                unittest.mock.call("scrapes_log"),
            ],
            cliente.table.call_args_list,
        )


if __name__ == "__main__":
    unittest.main()