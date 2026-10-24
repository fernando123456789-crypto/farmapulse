"""Selenium sobre la aplicación desplegada, sin servidor local ni respuestas simuladas."""

import json
import os
from pathlib import Path
import unittest

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait

import session_cache

_sessions = {}

credentials_file = Path(__file__).with_name('.env.selenium')
if credentials_file.exists():
    for line in credentials_file.read_text(encoding='utf-8-sig').splitlines():
        name, separator, value = line.partition('=')
        if separator and name.strip() in {
            'SELENIUM_USER_EMAIL', 'SELENIUM_USER_PASSWORD',
            'SELENIUM_ADMIN_EMAIL', 'SELENIUM_ADMIN_PASSWORD',
        }:
            os.environ.setdefault(name.strip(), value.strip())


class RenderCase(unittest.TestCase):
    base_url = 'https://farmapulse.onrender.com'

    def setUp(self):
        options = webdriver.ChromeOptions()
        options.page_load_strategy = 'eager'
        options.add_argument('--window-size=1440,1000')
        if os.getenv('SELENIUM_HEADLESS') == '1':
            options.add_argument('--headless=new')
        self.driver = webdriver.Chrome(options=options)
        self.addCleanup(self.driver.quit)
        self.driver.set_page_load_timeout(90)
        self.driver.set_script_timeout(45)
        self.wait = WebDriverWait(self.driver, 45)
        self.open('/comparador')

    def open(self, path):
        self.driver.get(self.base_url + path)
        self.wait.until(lambda driver: driver.execute_script('return !!window.FarmaPulseAuth'))
        self.assertTrue(self.driver.current_url.startswith(self.base_url + '/'))
        print(f'\nTítulo: {self.driver.title}', flush=True)
        print(f'URL: {self.driver.current_url.split("#", 1)[0]}', flush=True)

    def element(self, element_id):
        return self.driver.find_element(By.ID, element_id)

    def css(self, selector):
        return self.driver.find_element(By.CSS_SELECTOR, selector)

    def click(self, selector):
        button = self.wait.until(EC.element_to_be_clickable((By.CSS_SELECTOR, selector)))
        self.driver.execute_script("arguments[0].scrollIntoView({block:'center',behavior:'instant'})", button)
        self.wait.until(lambda driver: driver.execute_script(
            'const e=arguments[0],r=e.getBoundingClientRect(),t=document.elementFromPoint(r.x+r.width/2,r.y+r.height/2);return e===t||e.contains(t)', button))
        button.click()

    def fill(self, selector, value):
        field = self.visible(selector)
        field.clear()
        field.send_keys(value)

    def visible(self, selector):
        return self.wait.until(EC.visibility_of_element_located((By.CSS_SELECTOR, selector)))

    def hidden(self, selector):
        self.wait.until(EC.invisibility_of_element_located((By.CSS_SELECTOR, selector)))

    def text(self, selector, expected):
        self.wait.until(EC.text_to_be_present_in_element((By.CSS_SELECTOR, selector), expected))
        self.assertTrue(self.css(selector).is_displayed())

    def login(self, admin=False):
        role = 'ADMIN' if admin else 'USER'
        email = os.getenv(f'SELENIUM_{role}_EMAIL')
        password = os.getenv(f'SELENIUM_{role}_PASSWORD')
        if not email or not password:
            self.fail(f'Faltan las credenciales locales SELENIUM_{role}_EMAIL/PASSWORD')
        cached = _sessions.get(email) or session_cache.load(self.base_url, email)
        if cached:
            session = json.loads(cached)
            validation = self.driver.execute_async_script('''
                const token=arguments[0], done=arguments[arguments.length-1];
                fetch('/api/auth/sesion', {headers:{Authorization:'Bearer '+token}})
                  .then(async response => done({status:response.status, data:await response.json()}))
                  .catch(() => done({status:0}));
            ''', session['access_token'])
            self.assertIn(validation['status'], (200, 401), 'Render no pudo validar la sesión de pruebas')
            if validation.get('data', {}).get('autenticado'):
                session['es_admin'] = validation['data'].get('es_admin') is True
                cached = json.dumps(session)
                _sessions[email] = cached
                self.driver.execute_script("sessionStorage.setItem('farmapulse_sesion', arguments[0])", cached)
                self.driver.refresh()
                self.visible('#navAuthAutenticado')
                self.assertEqual(self.element('navCorreoUsuario').text, email)
                print('Acceso: sesión real validada en Render.', flush=True)
                return
            _sessions.pop(email, None)
            session_cache.remove(self.base_url, email)
        self.click('#btnAbrirLogin')
        self.fill('#formLogin [name=email]', email)
        self.fill('#formLogin [name=password]', password)
        self.click('#formLogin button[type=submit]')
        self.wait.until(lambda driver: self.element('navAuthAutenticado').is_displayed()
                        or self.css('#formLogin [data-error]').is_displayed())
        self.assertTrue(self.element('navAuthAutenticado').is_displayed(),
                        'Render rechazó el acceso: ' + self.css('#formLogin [data-error]').text)
        self.hidden('#modalLogin')
        self.assertEqual(self.element('navCorreoUsuario').text, email)
        _sessions[email] = self.driver.execute_script("return sessionStorage.getItem('farmapulse_sesion')")
        session_cache.save(self.base_url, email, _sessions[email])

    def forget_login(self):
        email = os.getenv('SELENIUM_USER_EMAIL')
        _sessions.pop(email, None)
        session_cache.remove(self.base_url, email)

    def search(self, term='Paracetamol', enter=False):
        seen = self.driver.execute_script("return sessionStorage.getItem('farmapulse_sugerencia_login_vista')")
        # Igual que By.name('q') en el ejemplo: localizar el campo y escribir.
        producto = self.wait.until(EC.visibility_of_element_located((By.ID, 'inputProducto')))
        producto.clear()
        producto.send_keys(term)
        if enter:
            producto.send_keys(Keys.ENTER)
        else:
            self.click('#btnBuscar')
        self.hidden('#loadingState')
        self.assertNotIn('Ocurrió un problema', self.element('tablaResultados').text,
                         'La búsqueda real de Render no respondió correctamente')
        if not seen and not self.element('navAuthAutenticado').is_displayed():
            self.visible('#modalSugerenciaLogin')
            producto.send_keys(Keys.ESCAPE)
            self.hidden('#modalSugerenciaLogin')

    def add_product(self):
        self.search()
        buttons = self.driver.find_elements(By.CSS_SELECTOR, '#tablaResultados .btn-carrito-toggle')
        self.assertTrue(buttons, 'Render debe devolver al menos un producto comprable')
        price = float(buttons[0].get_attribute('data-precio-empaque'))
        self.click('#tablaResultados .btn-carrito-toggle')
        self.text('#carritoContador', '1')
        return price

    def checkout(self):
        self.login()
        price = self.add_product()
        self.click('#btnComprar')
        self.visible('#modalCheckout')
        return price
