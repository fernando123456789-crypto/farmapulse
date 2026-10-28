"""Los casos funcionales establecidos a los requisitos de FarmaPulse."""

import os
import unittest

from selenium import webdriver
from selenium.webdriver.common.by import By

from pages.autenticacion import AutenticacionPage
from pages.comparador import ComparadorPage


class PruebasFuncionales(unittest.TestCase):
    def setUp(self):
        options = webdriver.ChromeOptions()
        options.page_load_strategy = "eager"
        options.add_argument("--window-size=1440,1000")
        if os.getenv("SELENIUM_HEADLESS") == "1":
            options.add_argument("--headless=new")
        self.driver = webdriver.Chrome(options=options)
        self.addCleanup(self.driver.quit)
        self.driver.set_page_load_timeout(90)
        self.comparador = ComparadorPage(self.driver)
        self.auth = AutenticacionPage(self.driver)
        self.comparador.abrir("https://farmapulse.onrender.com")
        print(f"\nTítulo: {self.driver.title}\nURL: {self.driver.current_url}", flush=True)

    def test_rf01_busqueda_por_nombre(self):
        productos = self.comparador.buscar("Paracetamol")
        self.assertTrue(productos, "La búsqueda debe mostrar productos disponibles")
        self.assertTrue(
            all(
                "paracetamol" in (p.get_attribute("data-medicamento") or "").lower()
                or "paracetamol" in (p.get_attribute("data-dci") or "").lower()
                for p in productos
            ),
            "Cada resultado debe coincidir por nombre o principio activo",
        )

    def test_rf01_filtrar_por_farmacia(self):
        productos = self.comparador.buscar("Paracetamol", farmacia="Mifarma")
        self.assertTrue(productos, "Se esperan resultados para la farmacia seleccionada")
        self.assertTrue(all("mifarma" in p.get_attribute("data-farmacia").lower() for p in productos))

    def test_rf01_filtrar_por_farmacias_del_peru(self):
        farmacias = self.comparador.buscar_farmacias_en_tabla("Paracetamol", "Farmacias del Peru")
        self.assertTrue(farmacias, "Se esperan resultados para la farmacia seleccionada")
        self.assertTrue(
            all("farmacias del peru" in celda.text.lower() for celda in farmacias),
            "Las filas deben corresponder a la farmacia seleccionada",
        )

    def test_rf02_precios_ordenados_de_menor_a_mayor(self):
        self.comparador.buscar("Paracetamol")
        precios = self.comparador.precios()
        self.assertGreaterEqual(len(precios), 2, "Se necesitan al menos dos precios para comparar")
        self.assertEqual(precios, sorted(precios), "Los precios deben aparecer en orden ascendente")

    def test_rf05_agregar_y_retirar_producto(self):
        self.comparador.buscar("Paracetamol")
        self.comparador.agregar_primer_producto()
        self.assertNotEqual(self.driver.find_element(*self.comparador.TOTAL).text, "S/ 0.00")

        self.comparador.retirar_producto()

        self.assertFalse(self.driver.find_elements(By.CSS_SELECTOR, "#miCarrito .receta-card"))
        self.assertFalse(self.driver.find_element(*self.comparador.COMPRAR).is_enabled())

    def test_rf05_mostrar_despacho_a_domicilio(self):
        correo, clave = self.cuenta_de_prueba()
        self.assertTrue(self.auth.iniciar_sesion(correo, clave), "La cuenta de prueba debe iniciar sesión")
        self.comparador.buscar("Paracetamol")
        self.comparador.agregar_primer_producto()

        self.comparador.click(self.comparador.COMPRAR)

        self.comparador.visible(self.comparador.CHECKOUT)
        self.assertEqual(self.comparador.distritos_de_entrega(), {"San Borja", "San Luis", "La Victoria"})
        self.assertTrue(self.comparador.visible((By.ID, "checkoutDireccion")).is_displayed())

    def test_rf06_registro_rechaza_clave_sin_numero(self):
        error = self.auth.registrar("prueba@example.invalid", "Abcdefghijk!")
        self.assertIn("número", error.text.lower())
        self.assertTrue(self.driver.find_element(*self.auth.REGISTRO).is_displayed())

    def test_rf06_registro_rechaza_clave_demasiado_corta(self):
        self.auth.click(self.auth.ABRIR_REGISTRO)
        self.auth.fill(self.auth.REGISTRO_EMAIL, "prueba@example.invalid")
        self.auth.fill(self.auth.REGISTRO_CLAVE, "Abcdefghijk")
        self.auth.click(self.auth.ENVIAR_REGISTRO)

        clave = self.driver.find_element(*self.auth.REGISTRO_CLAVE)
        self.assertEqual(clave.get_attribute("minlength"), "12")
        self.assertFalse(self.driver.execute_script("return arguments[0].checkValidity()", clave))
        self.assertTrue(self.driver.find_element(*self.auth.REGISTRO).is_displayed())

    def test_rf06_inicio_sesion_con_cuenta_de_prueba(self):
        correo, clave = self.cuenta_de_prueba()

        acceso = self.auth.iniciar_sesion(correo, clave)

        self.assertTrue(acceso, "El inicio de sesión debe aceptar la cuenta de prueba")
        self.assertEqual(self.auth.visible(self.auth.USUARIO).text, correo)


    def cuenta_de_prueba(self):
        correo = os.getenv("SELENIUM_USER_EMAIL")
        clave = os.getenv("SELENIUM_USER_PASSWORD")
        if not correo or not clave:
            self.skipTest("Faltan las credenciales locales de la cuenta de prueba")
        return correo, clave
        self.assertTrue(acceso, "El inicio de sesión debe aceptar la cuenta de prueba")
        self.assertEqual(self.auth.visible(self.auth.USUARIO).text, correo)


if __name__ == "__main__":
    unittest.main(verbosity=2)
