import unittest
from unittest.mock import MagicMock

import requests

from dao.captura_precios_dao import CapturaPreciosDAO
from dao.receta_dao import RecetaDAO, RecetaDAOError


class RecetaDAOTests(unittest.TestCase):
    URL = "https://proyecto.supabase.co"

    def test_guardar_usa_supabase_con_token_del_usuario(self):
        registro = {"id": "receta-1", "usuario_id": "usuario-1"}
        sesion = MagicMock()
        sesion.post.return_value.json.return_value = [registro]
        dao = RecetaDAO(self.URL, "anon-key", session=sesion)

        fuente, datos = dao.guardar(registro, "token-usuario")

        self.assertEqual(("supabase", [registro]), (fuente, datos))
        args, kwargs = sesion.post.call_args
        self.assertEqual(f"{self.URL}/rest/v1/listas_recetas", args[0])
        self.assertEqual("Bearer token-usuario", kwargs["headers"]["Authorization"])
        self.assertEqual(registro, kwargs["json"])

    def test_listar_filtra_por_usuario_en_supabase(self):
        sesion = MagicMock()
        sesion.get.return_value.json.return_value = []
        dao = RecetaDAO(self.URL, "anon-key", session=sesion)

        dao.listar_por_usuario("usuario-1", "token-usuario")

        params = sesion.get.call_args.kwargs["params"]
        self.assertEqual("eq.usuario-1", params["usuario_id"])
        self.assertEqual("creado_en.desc", params["order"])

    def test_guardar_y_listar_usan_memoria_sin_supabase(self):
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

    def test_si_supabase_falla_no_se_oculta_con_memoria(self):
        sesion = MagicMock()
        sesion.post.side_effect = requests.ConnectionError("sin conexión")
        memoria = []
        dao = RecetaDAO(self.URL, "anon-key", memoria, session=sesion)

        with self.assertRaises(RecetaDAOError):
            dao.guardar({"id": "receta-1", "usuario_id": "usuario-1"}, "token")

        self.assertEqual([], memoria)


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