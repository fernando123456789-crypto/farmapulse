"""Contratos de integración reales y controles de acceso complementarios."""
import base64
import json
import os
import unittest
from decimal import Decimal
from urllib.parse import urlencode

from servicios import PROJECT, ServiciosPage, cargar_configuracion


class BaseIntegracion(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cargar_configuracion()
        cls.page = ServiciosPage()
        cls.addClassCleanup(cls.page.driver.quit)
        cls.page.abrir()

    def setUp(self):
        self.mediciones = []

    def respuesta(self, result, status=200):
        self.mediciones.append({"http": result["status"], "ms": result["ms"],
                                "respuesta_reutilizada": result.get("reutilizada", False)})
        self.assertEqual(result["status"], status, "Verifico el estado HTTP esperado")
        self.assertIsInstance(result["data"], dict, "Espero un objeto JSON")
        return result["data"]


class ServiciosPublicosTests(BaseIntegracion):
    def precios_mifarma(self):
        return self.page.precargar("precios", "/api/buscar?" + urlencode({"producto":"Paracetamol", "farmacia":"Mifarma"}))

    def test_01_farmacias_devuelven_datos_reales(self):
        """Farmacias: compruebo respuesta real y campos mínimos del contrato."""
        data = self.respuesta(self.precios_mifarma())
        self.assertEqual(data.get("fuente"), "farmacias", "No acepto datos demo como integración real")
        self.assertTrue(data.get("resultados"), "Espero productos de la farmacia consultada")
        for item in data["resultados"]:
            self.assertTrue(all(key in item for key in ("medicamento", "farmacia", "precio_unitario")))
            self.assertGreater(Decimal(str(item["precio_unitario"])), 0)

    def test_02_farmacias_respetan_el_filtro(self):
        """Farmacias: verifico que el proveedor seleccionado corresponda a los datos."""
        data = self.respuesta(self.precios_mifarma())
        self.assertEqual(data.get("fuente"), "farmacias")
        self.assertTrue(data.get("resultados"))
        self.assertTrue(all("mifarma" in item["farmacia"].casefold() for item in data["resultados"]))

    def test_03_mercado_pago_carga_el_sdk(self):
        """Mercado Pago: verifico la carga del SDK externo en el navegador."""
        self.page.wait.until(lambda driver: driver.execute_script("return typeof window.MercadoPago === 'function'"))
        self.assertTrue(self.page.driver.execute_script("return typeof window.MercadoPago === 'function'"))

    def test_04_mercado_pago_configuracion_de_prueba(self):
        """Mercado Pago: compruebo la disponibilidad declarada por el servidor."""
        data = self.respuesta(self.page.consultar("/api/config"))
        self.assertTrue(data.get("pasarela_configurada"), "Espero una pasarela de pruebas disponible")
        self.assertTrue(data.get("mercado_pago_public_key"))


class ServiciosAutenticadosTests(BaseIntegracion):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        correo, clave = os.getenv("SELENIUM_USER_EMAIL"), os.getenv("SELENIUM_USER_PASSWORD")
        if not correo or not clave:
            raise unittest.SkipTest("Configuro primero la cuenta local de prueba")
        cls.page.iniciar_sesion(correo, clave)
        raw = cls.page.driver.execute_script("return JSON.parse(sessionStorage.getItem('farmapulse_sesion')).access_token")
        claims = json.loads(base64.urlsafe_b64decode(raw.split(".")[1] + "=" * (-len(raw.split(".")[1]) % 4)))
        if claims.get("iss") != f"https://{PROJECT}.supabase.co/auth/v1":
            raise AssertionError("La sesión no corresponde al proyecto Supabase indicado")
        cls.usuario_id = claims["sub"]


    def historial(self):
        return self.page.precargar("historial", "/api/receta/historial", autenticado=True)

    def producto(self):
        result = self.page.precargar("producto", "/api/buscar?producto=Paracetamol&farmacia=Mifarma", autenticado=True)
        data = self.respuesta(result)
        self.assertEqual(data.get("fuente"), "farmacias")
        items = [item for item in data.get("resultados", []) if item.get("comprable") and item.get("cotizacion")]
        self.assertTrue(items, "Espero un producto real con cotización firmada")
        return items[0]

    def direccion(self):
        return self.page.precargar("direccion", "/api/direcciones/validar", method="POST", autenticado=True,
                                   body={"latitud":-12.107,"longitud":-76.999,"direccion":"Avenida San Borja Norte - punto de prueba"})

    def cliente(self):
        dni = os.getenv("TEST_DNI", "")
        nombres = [os.getenv(key, "") for key in ("TEST_NOMBRES", "TEST_APELLIDOS")]
        if not (dni.isascii() and dni.isdigit() and len(dni) == 8
                and all(value and not value.startswith("PONER_") for value in nombres)):
            self.skipTest("Configuro la identidad autorizada en el archivo local")
        address = self.respuesta(self.direccion())
        return {"nombres":os.environ["TEST_NOMBRES"], "apellidos":os.environ["TEST_APELLIDOS"],
                "dni":os.environ["TEST_DNI"], "telefono":"900000000", "distrito":address["distrito"],
                "direccion":address["direccion"], "place_id":address["place_id"],
                "direccion_validacion":address["validacion"]}

    def test_05_auth_sesion_validada(self):
        """Supabase Auth: compruebo que FarmaPulse reconozca la sesión real."""
        data = self.respuesta(self.page.consultar("/api/auth/sesion", autenticado=True))
        self.assertTrue(data.get("autenticado"))
        self.assertTrue(data.get("usuario", {}).get("id") == self.usuario_id)

    def test_06_auth_token_invalido(self):
        """Supabase Auth: compruebo que un token inválido no autentique al cliente."""
        data = self.respuesta(self.page.consultar("/api/auth/sesion", token_invalido=True))
        self.assertFalse(data.get("autenticado"))

    def test_07_auth_sin_token(self):
        """Control de acceso: compruebo el comportamiento sin credenciales."""
        data = self.respuesta(self.page.consultar("/api/auth/sesion"))
        self.assertFalse(data.get("autenticado"))

    def test_08_db_historial_desde_supabase(self):
        """PostgreSQL: verifico que el historial proceda de Supabase y no de memoria."""
        data = self.respuesta(self.historial())
        self.assertEqual(data.get("fuente"), "supabase")
        self.assertIsInstance(data.get("data"), list)

    def test_09_db_registros_del_usuario(self):
        """PostgreSQL: compruebo la pertenencia de los registros devueltos."""
        rows = self.respuesta(self.historial()).get("data")
        self.assertIsInstance(rows, list)
        if not rows:
            self.skipTest("La cuenta no tiene registros; no doy por comprobado el aislamiento con una lista vacía")
        self.assertTrue(all(row.get("usuario_id") == self.usuario_id for row in rows))

    def test_10_db_exige_sesion(self):
        """Control de acceso: compruebo el rechazo del historial anónimo."""
        data = self.respuesta(self.page.consultar("/api/receta/historial"), 401)
        self.assertFalse(data.get("ok"))

    def test_11_cotizacion_producto_real(self):
        """Farmacias y checkout: verifico la aceptación y los importes de una cotización real."""
        item = self.producto()
        data = self.respuesta(self.page.consultar("/api/checkout/cotizar", method="POST", body={"productos":[item]}, autenticado=True))
        self.assertTrue(data.get("ok"))
        self.assertEqual(Decimal(data["subtotal"]) + Decimal(data["delivery"]), Decimal(data["total"]))

    def mapas(self):
        return self.page.precargar("mapas", "/api/direcciones/sugerencias", method="POST", autenticado=True,
                                   body={"texto":"Avenida San Borja Norte", "distrito":"San Borja"})

    def test_12_mapas_respuesta_del_geocodificador(self):
        """Photon: compruebo sugerencias reales con descripción y coordenadas."""
        data = self.respuesta(self.mapas())
        self.assertTrue(data.get("sugerencias"), "Espero sugerencias del servicio externo")
        for item in data["sugerencias"]:
            self.assertTrue(item.get("descripcion"))
            self.assertIsInstance(item.get("latitud"), (int, float))
            self.assertIsInstance(item.get("longitud"), (int, float))

    def test_13_mapas_respeta_distrito(self):
        """Photon y reparto: verifico el distrito de las sugerencias recibidas."""
        data = self.respuesta(self.mapas())
        self.assertTrue(data.get("sugerencias"))
        self.assertTrue(all(item.get("distrito") == "San Borja" for item in data["sugerencias"]))

    def test_14_dni_validado_por_proveedor(self):
        """Decolecta: compruebo la identidad autorizada mediante el backend real."""
        body = {**self.cliente(), "productos":[self.producto()]}
        data = self.respuesta(self.page.consultar("/api/checkout/orden", method="POST", body=body, autenticado=True))
        self.assertTrue(data.get("ok"))
        self.assertTrue(data.get("pagador", {}).get("dni") == os.environ["TEST_DNI"])
        self.assertTrue(data.get("orden_firma"))

    def test_15_dni_formato_invalido(self):
        """Validación previa: compruebo el rechazo local sin consultar una identidad ajena."""
        body = {**self.cliente(), "dni":"123", "productos":[self.producto()]}
        data = self.respuesta(self.page.consultar("/api/checkout/orden", method="POST", body=body, autenticado=True), 400)
        self.assertFalse(data.get("ok"))
