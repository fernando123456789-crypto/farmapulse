"""Flujos de usuario sobre Render mediante identificadores y acciones reales."""

import os

from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import Select

from render_support import RenderCase


class PublicRenderTests(RenderCase):
    def test_cambiar_entre_login_y_registro(self):
        self.click('#btnAbrirLogin')
        self.click('#modalLogin [data-cambiar-a-registro]')
        self.visible('#modalRegistro')
        self.hidden('#modalLogin')
        self.click('#modalRegistro [data-cambiar-a-login]')
        self.visible('#modalLogin')
        self.hidden('#modalRegistro')

    def test_cerrar_login_con_su_boton(self):
        self.click('#btnAbrirLogin')
        self.click('#modalLogin button[data-cerrar-modal]')
        self.hidden('#modalLogin')

    def test_email_invalido_impide_enviar_registro(self):
        self.click('#btnAbrirRegistro')
        self.fill('#formRegistro [name=email]', 'correo-invalido')
        self.fill('#formRegistro [name=password]', 'ClaveSegura123!')
        self.click('#formRegistro button[type=submit]')
        self.assertFalse(self.driver.execute_script("return document.querySelector('#formRegistro [name=email]').validity.valid"))
        self.assertTrue(self.element('modalRegistro').is_displayed())

    def test_recuperacion_permite_volver_al_login(self):
        self.click('#btnAbrirLogin')
        self.click('#formLogin [data-recuperar-contrasena]')
        self.visible('#modalRecuperarCuenta')
        self.click('#formRecuperarCuenta [data-cambiar-a-login]')
        self.visible('#modalLogin')
        self.hidden('#modalRecuperarCuenta')

    def test_historial_administrativo_exige_sesion(self):
        self.open('/admin')
        self.text('#admPuertaTitulo', 'Inicia sesión')
        self.assertFalse(self.element('admPanel').is_displayed())


class SearchRenderTests(RenderCase):
    def test_buscar_ordenar_precios_y_mostrar_ahorro(self):
        self.search()
        buttons = self.driver.find_elements(By.CSS_SELECTOR, '#tablaResultados .btn-carrito-toggle')
        self.assertTrue(buttons, 'Se esperan resultados reales comprables para Paracetamol')
        prices = [float(button.get_attribute('data-precio-unitario')) for button in buttons]
        self.assertEqual(prices, sorted(prices))
        self.visible('#tablaResultados .fila-mejor-precio')
        self.visible('#panelAhorro')

    def test_buscar_con_enter(self):
        self.search(enter=True)
        self.assertTrue(self.driver.find_elements(By.CSS_SELECTOR, '#tablaResultados .btn-carrito-toggle'))

    def test_filtrar_por_farmacia(self):
        self.fill('#inputFarmacia', 'Mifarma')
        self.search()
        buttons = self.driver.find_elements(By.CSS_SELECTOR, '#tablaResultados .btn-carrito-toggle')
        self.assertTrue(buttons, 'Mifarma debe devolver productos para la búsqueda real')
        self.assertTrue(all('mifarma' in button.get_attribute('data-farmacia').lower() for button in buttons))

    def test_agregar_recargar_y_quitar_desde_el_carrito(self):
        price = self.add_product()
        self.assertEqual(self.element('carritoTotalMini').text, f'S/ {price:.2f}')
        self.driver.refresh()
        self.text('#carritoContador', '1')
        self.assertEqual(self.element('carritoTotalMini').text, f'S/ {price:.2f}')
        self.click('#miCarrito .btn-quitar-carrito')
        self.text('#miCarrito', 'Aún no has agregado productos')
        self.assertFalse(self.element('btnComprar').is_enabled())

    def test_quitar_desde_la_tabla(self):
        self.add_product()
        self.text('#tablaResultados .btn-carrito-toggle', 'Quitar')
        self.click('#tablaResultados .btn-carrito-toggle')
        self.assertEqual(len(self.driver.find_elements(By.CSS_SELECTOR, '#miCarrito .receta-card')), 0,
                         'Un clic en Quitar debe retirar el producto del carrito')

    def test_comprar_como_invitado_solicita_login(self):
        self.add_product()
        self.click('#btnComprar')
        self.visible('#modalLogin')
        self.assertFalse(self.element('modalCheckout').is_displayed())


class AccountRenderTests(RenderCase):
    def test_cancelar_eliminacion_conserva_la_cuenta(self):
        self.login()
        self.click('#btnEliminarCuenta')
        self.visible('#modalEliminarCuenta')
        self.click('#formEliminarCuenta button[data-cerrar-modal]')
        self.hidden('#modalEliminarCuenta')
        self.assertTrue(self.element('navAuthAutenticado').is_displayed())

    def test_panel_respeta_el_rol_de_la_cuenta(self):
        self.login()
        admin = self.driver.execute_script('return window.FarmaPulseAuth.esAdmin()')
        self.open('/admin')
        if admin:
            self.visible('#admPanel')
            self.text('#admRegistros', 'registro(s)')
        else:
            self.text('#admPuertaTitulo', 'Acceso restringido')
            self.assertFalse(self.element('admPanel').is_displayed())


class CheckoutRenderTests(RenderCase):
    def test_resumen_campos_seguros_y_distritos_permitidos(self):
        price = self.checkout()
        self.assertEqual(self.element('checkoutSubtotal').text, f'S/ {price:.2f}')
        self.assertEqual(self.element('checkoutDelivery').text, 'S/ 5.00')
        self.assertEqual(self.element('checkoutTotal').text, f'S/ {price + 5:.2f}')
        districts = {option.text for option in Select(self.element('checkoutDistrito')).options if option.get_attribute('value')}
        self.assertEqual(districts, {'San Borja', 'San Luis', 'La Victoria'})
        for field in ('Numero', 'Vencimiento', 'Seguridad'):
            self.visible(f'#mercadoPago{field} iframe')
        self.assertFalse(self.element('mercadoPagoPagar').is_enabled())


    def test_cerrar_reabrir_checkout_conserva_el_carrito(self):
        price = self.checkout()
        self.visible('#mercadoPagoNumero iframe')
        self.click('#modalCheckout button[data-cerrar-checkout]')
        self.hidden('#modalCheckout')
        self.assertEqual(self.element('carritoTotalMini').text, f'S/ {price:.2f}')
        self.click('#btnComprar')
        self.visible('#mercadoPagoNumero iframe')
        self.assertFalse(self.element('mercadoPagoPagar').is_enabled())


class AdminRenderTests(RenderCase):
    def admin(self):
        self.login(admin=bool(os.getenv('SELENIUM_ADMIN_EMAIL')))
        self.assertTrue(self.driver.execute_script('return window.FarmaPulseAuth.esAdmin()'),
                        'Este grupo requiere una cuenta administradora de Render')
        self.open('/admin')
        self.visible('#admPanel')
        self.text('#admRegistros', 'registro(s)')

    def test_historial_y_resumen_son_visibles(self):
        self.admin()
        for field in ('admCompras', 'admIngresos', 'admUnidades', 'admTicket'):
            self.assertNotEqual(self.element(field).text, '—')
        self.assertTrue(self.driver.find_elements(By.CSS_SELECTOR, '#admFilas tr'))

    def test_busqueda_sin_coincidencias_y_limpiar(self):
        self.admin()
        self.fill('#admBuscar', 'e2e-sin-coincidencias-7d49b')
        self.text('#admFilas', 'No hay compras que coincidan')
        self.text('#admRegistros', '0 registro(s)')
        self.click('#admLimpiar')
        self.wait.until(lambda driver: self.element('admBuscar').get_attribute('value') == '')
        self.text('#admRegistros', 'registro(s)')

    def test_pendientes_no_generan_ingresos_aprobados(self):
        self.admin()
        Select(self.element('admEstado')).select_by_value('pending')
        self.text('#admIngresos', 'S/ 0.00')
        self.assertEqual(self.element('admEstado').get_attribute('value'), 'pending')


class ZSessionRenderTests(RenderCase):
    def test_login_recarga_y_cierre_de_sesion(self):
        self.login()
        self.assertIsNone(self.driver.execute_script("return localStorage.getItem('farmapulse_sesion')"))
        self.assertFalse(self.driver.execute_script("return 'refresh_token' in JSON.parse(sessionStorage.getItem('farmapulse_sesion'))"))
        self.driver.refresh()
        self.visible('#navAuthAutenticado')
        self.click('#btnCerrarSesion')
        self.visible('#navAuthInvitado')
        self.assertIsNone(self.driver.execute_script("return sessionStorage.getItem('farmapulse_sesion')"))
        self.forget_login()
