"""Interacciones de Selenium con la aplicación y sus respuestas HTTP reales."""
import os
from pathlib import Path

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait

BASE_URL = "https://farmapulse.onrender.com"
PROJECT = "gxknyrzcvgddxzfhqyzg"


def cargar_configuracion():
    path = Path(__file__).with_name(".env.interoperabilidad")
    if path.exists():
        for line in path.read_text(encoding="utf-8-sig").splitlines():
            key, separator, value = line.partition("=")
            if separator and key.startswith(("SELENIUM_", "TEST_")):
                os.environ.setdefault(key.strip(), value.strip())


class ServiciosPage:
    def __init__(self):
        options = webdriver.ChromeOptions()
        options.page_load_strategy = "eager"
        options.add_argument("--window-size=1440,1000")
        if os.getenv("SELENIUM_HEADLESS") == "1":
            options.add_argument("--headless=new")
        self.driver = webdriver.Chrome(options=options)
        self.driver.set_page_load_timeout(90)
        self.driver.set_script_timeout(75)
        self.wait = WebDriverWait(self.driver, 45)
        self.cache = {}

    def abrir(self):
        self.driver.get(BASE_URL + "/comparador")
        self.wait.until(lambda driver: driver.execute_script("return !!window.FarmaPulseAuth"))

    def iniciar_sesion(self, correo, clave):
        self.wait.until(EC.element_to_be_clickable((By.ID, "btnAbrirLogin"))).click()
        for name, value in (("email", correo), ("password", clave)):
            field = self.wait.until(EC.visibility_of_element_located((By.CSS_SELECTOR, f"#formLogin [name='{name}']")))
            field.send_keys(value)
        self.driver.find_element(By.CSS_SELECTOR, "#formLogin button[type='submit']").click()
        self.wait.until(lambda driver: driver.find_element(By.ID, "navAuthAutenticado").is_displayed()
                        or driver.find_element(By.CSS_SELECTOR, "#formLogin [data-error]").is_displayed())
        if not self.driver.find_element(By.ID, "navAuthAutenticado").is_displayed():
            raise AssertionError("La cuenta de prueba no pudo iniciar sesión; reviso credenciales, confirmación y límite de acceso.")
        self.wait.until(EC.invisibility_of_element_located((By.ID, "modalLogin")))

    def consultar(self, path, method="GET", body=None, autenticado=False, token_invalido=False):
        if not path.startswith("/api/"):
            raise ValueError("Solo envío solicitudes a las APIs de FarmaPulse")
        result = self.driver.execute_async_script("""
          const [path, method, body, authenticated, invalid] = arguments;
          const done = arguments[arguments.length - 1];
          const headers = {Accept:'application/json'};
          if (body !== null) headers['Content-Type'] = 'application/json';
          if (authenticated) Object.assign(headers, window.FarmaPulseAuth.headersAuth());
          if (invalid) headers.Authorization = 'Bearer token-de-prueba-invalido';
          const start = performance.now();
          fetch(path, {method, headers, body:body === null ? undefined : JSON.stringify(body),
                       signal:AbortSignal.timeout(60000)})
            .then(async response => {
              const data = await response.json();
              done({status:response.status, data, ms:Math.round(performance.now()-start)});
            }).catch(() => done({status:0, data:null, ms:Math.round(performance.now()-start)}));
        """, path, method, body, autenticado, token_invalido)
        return result

    def precargar(self, key, path, **kwargs):
        reutilizada = key in self.cache
        if key not in self.cache:
            self.cache[key] = self.consultar(path, **kwargs)
        return {**self.cache[key], "reutilizada": reutilizada}
