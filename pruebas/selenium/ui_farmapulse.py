"""Flujos públicos en Chrome con Selenium y esperas por condiciones visibles."""

import os
import unittest

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import Select, WebDriverWait


class FarmaPulseBrowserTests(unittest.TestCase):
    def setUp(self):
        self.base_url = "https://farmapulse.onrender.com"
        options = webdriver.ChromeOptions()
        options.add_argument("--window-size=1440,1000")
        if os.getenv("SELENIUM_HEADLESS") == "1":
            options.add_argument("--headless=new")
        self.driver = webdriver.Chrome(options=options)
        self.addCleanup(self.driver.quit)
        self.driver.set_page_load_timeout(90)
        self.wait = WebDriverWait(self.driver, 30)
        self.driver.get(self.base_url + "/comparador")
        self.wait.until(EC.element_to_be_clickable((By.ID, "inputProducto")))
        print(f"\nTítulo: {self.driver.title}", flush=True)
        print(f"URL: {self.driver.current_url}", flush=True)

    def element(self, element_id):
        return self.driver.find_element(By.ID, element_id)

    def click(self, by, value):
        self.wait.until(EC.element_to_be_clickable((by, value))).click()

    def test_navegar_del_inicio_al_comparador(self):
        self.driver.get(self.base_url + "/")

        self.click(By.CSS_SELECTOR, "header a[href='/comparador']")

        self.wait.until(EC.url_to_be(self.base_url + "/comparador"))
        self.assertTrue(self.wait.until(EC.visibility_of_element_located((By.ID, "inputProducto"))))

    def test_seleccionar_un_distrito_de_lima(self):
        district = Select(self.wait.until(EC.element_to_be_clickable((By.ID, "selectDistrito"))))
        option = next(option for option in district.options if option.text.upper() == "SAN BORJA")

        district.select_by_value(option.get_attribute("value"))

        self.assertEqual(district.first_selected_option.text.upper(), "SAN BORJA")

    def test_limpiar_los_filtros_de_busqueda(self):
        producto = self.wait.until(
            EC.visibility_of_element_located((By.ID, "inputProducto"))
        )
        farmacia = self.driver.find_element(By.ID, "inputFarmacia")
        producto.send_keys("Paracetamol")
        farmacia.send_keys("Inkafarma")

        self.click(By.ID, "btnLimpiar")

        self.assertEqual(producto.get_attribute("value"), "")
        self.assertEqual(farmacia.get_attribute("value"), "")
        self.assertIn("Realiza una búsqueda", self.element("tablaResultados").text)

    def test_abrir_recuperacion_con_el_correo_del_login(self):
        self.click(By.ID, "btnAbrirLogin")
        self.wait.until(EC.visibility_of_element_located((By.ID, "formLogin")))
        self.driver.find_element(By.CSS_SELECTOR, "#formLogin [name='email']").send_keys("prueba@example.invalid")

        self.click(By.CSS_SELECTOR, "#formLogin [data-recuperar-contrasena]")

        self.wait.until(EC.visibility_of_element_located((By.ID, "modalRecuperarCuenta")))
        self.assertEqual(self.element("correoRecuperacion").get_attribute("value"), "prueba@example.invalid")
        self.assertFalse(self.element("modalLogin").is_displayed())

    def test_rechazar_registro_con_contrasena_sin_numero(self):
        self.click(By.ID, "btnAbrirRegistro")
        self.wait.until(EC.visibility_of_element_located((By.ID, "formRegistro")))
        self.driver.find_element(By.CSS_SELECTOR, "#formRegistro [name='email']").send_keys("prueba@example.invalid")
        self.driver.find_element(By.CSS_SELECTOR, "#formRegistro [name='password']").send_keys("Abcdefghijk!")

        self.click(By.CSS_SELECTOR, "#formRegistro button[type='submit']")

        error = self.wait.until(EC.visibility_of_element_located((By.CSS_SELECTOR, "#formRegistro [data-error]")))
        self.assertIn("número", error.text)
        self.assertTrue(self.element("modalRegistro").is_displayed())

    def test_carrito_vacio_no_habilita_la_compra(self):
        self.assertIn("Aún no has agregado productos", self.element("miCarrito").text)
        self.assertEqual(self.element("carritoTotalMini").text, "S/ 0.00")
        self.assertFalse(self.element("btnComprar").is_enabled())


if __name__ == "__main__":
    unittest.main(verbosity=2)
