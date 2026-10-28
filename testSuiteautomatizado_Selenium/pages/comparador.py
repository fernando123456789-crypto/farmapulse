"""Localizadores y acciones del comparador de FarmaPulse."""

from decimal import Decimal

from selenium.common.exceptions import TimeoutException
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import Select, WebDriverWait

from pages.base import BasePage


class ComparadorPage(BasePage):
    PRODUCTO = (By.ID, "inputProducto")
    FARMACIA = (By.ID, "inputFarmacia")
    BUSCAR = (By.ID, "btnBuscar")
    CARGANDO = (By.ID, "loadingState")
    RESULTADOS = (By.ID, "tablaResultados")
    PRODUCTOS = (By.CSS_SELECTOR, "#tablaResultados .btn-carrito-toggle")
    SUGERENCIA = (By.ID, "modalSugerenciaLogin")
    CARRITO = (By.ID, "miCarrito")
    TOTAL = (By.ID, "carritoTotalMini")
    COMPRAR = (By.ID, "btnComprar")
    CHECKOUT = (By.ID, "modalCheckout")
    DISTRITO_ENTREGA = (By.ID, "checkoutDistrito")

    def abrir(self, base_url):
        self.driver.get(f"{base_url}/comparador")
        self.visible(self.PRODUCTO)

    def buscar(self, producto, farmacia=None):
        self._enviar_busqueda(producto, farmacia)
        return self.wait.until(EC.visibility_of_all_elements_located(self.PRODUCTOS))

    def buscar_farmacias_en_tabla(self, producto, farmacia):
        self._enviar_busqueda(producto, farmacia)
        celdas = (By.CSS_SELECTOR, "#tablaResultados tr td:nth-child(3)")
        return self.wait.until(EC.visibility_of_all_elements_located(celdas))

    def _enviar_busqueda(self, producto, farmacia):
        # El identificador equivale al By.name("q") del ejemplo del profesor.
        vista = self.driver.execute_script(
            "return sessionStorage.getItem('farmapulse_sugerencia_login_vista')"
        )
        autenticado = self.driver.find_element(By.ID, "navAuthAutenticado").is_displayed()
        self.fill(self.PRODUCTO, producto)
        if farmacia:
            self.fill(self.FARMACIA, farmacia)
        self.click(self.BUSCAR)
        self.hidden(self.CARGANDO)
        if not vista and not autenticado:
            try:
                WebDriverWait(self.driver, 3).until(EC.visibility_of_element_located(self.SUGERENCIA))
            except TimeoutException:
                # La sugerencia es opcional y no determina el resultado de búsqueda.
                pass
            else:
                self.driver.find_element(*self.PRODUCTO).send_keys(Keys.ESCAPE)
                self.hidden(self.SUGERENCIA)

    def precios(self):
        return [
            Decimal(button.get_attribute("data-precio-unitario"))
            for button in self.driver.find_elements(*self.PRODUCTOS)
        ]

    def agregar_primer_producto(self):
        self.click(self.PRODUCTOS)
        return self.visible((By.CSS_SELECTOR, "#miCarrito .receta-card"))

    def retirar_producto(self):
        self.click((By.CSS_SELECTOR, "#miCarrito .btn-quitar-carrito"))
        self.wait.until(EC.text_to_be_present_in_element(self.CARRITO, "Aún no has agregado"))

    def distritos_de_entrega(self):
        return {
            option.text.strip()
            for option in Select(self.visible(self.DISTRITO_ENTREGA)).options
            if option.get_attribute("value")
        }
