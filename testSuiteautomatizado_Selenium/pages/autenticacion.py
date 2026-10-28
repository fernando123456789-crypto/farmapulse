"""Localizadores y acciones de registro e inicio de sesión."""

from selenium.webdriver.common.by import By
from pages.base import BasePage


class AutenticacionPage(BasePage):
    ABRIR_REGISTRO = (By.ID, "btnAbrirRegistro")
    REGISTRO = (By.ID, "modalRegistro")
    REGISTRO_EMAIL = (By.CSS_SELECTOR, "#formRegistro [name='email']")
    REGISTRO_CLAVE = (By.CSS_SELECTOR, "#formRegistro [name='password']")
    ENVIAR_REGISTRO = (By.CSS_SELECTOR, "#formRegistro button[type='submit']")
    ERROR_REGISTRO = (By.CSS_SELECTOR, "#formRegistro [data-error]")
    ABRIR_LOGIN = (By.ID, "btnAbrirLogin")
    LOGIN_EMAIL = (By.CSS_SELECTOR, "#formLogin [name='email']")
    LOGIN_CLAVE = (By.CSS_SELECTOR, "#formLogin [name='password']")
    ENVIAR_LOGIN = (By.CSS_SELECTOR, "#formLogin button[type='submit']")
    LOGIN_ERROR = (By.CSS_SELECTOR, "#formLogin [data-error]")
    USUARIO = (By.ID, "navCorreoUsuario")
    AUTENTICADO = (By.ID, "navAuthAutenticado")

    def registrar(self, correo, clave):
        self.click(self.ABRIR_REGISTRO)
        self.fill(self.REGISTRO_EMAIL, correo)
        self.fill(self.REGISTRO_CLAVE, clave)
        self.click(self.ENVIAR_REGISTRO)
        return self.visible(self.ERROR_REGISTRO)

    def iniciar_sesion(self, correo, clave):
        self.click(self.ABRIR_LOGIN)
        self.fill(self.LOGIN_EMAIL, correo)
        self.fill(self.LOGIN_CLAVE, clave)
        self.click(self.ENVIAR_LOGIN)
        self.wait.until(
            lambda driver: driver.find_element(*self.AUTENTICADO).is_displayed()
            or driver.find_element(*self.LOGIN_ERROR).is_displayed()
        )
        return self.driver.find_element(*self.AUTENTICADO).is_displayed()
