import base64
import hashlib
import json
import os
from pathlib import Path
import re
import unittest
from unittest.mock import patch

os.environ['SECRET_KEY'] = 'test-only-key-not-for-production-123456789'
os.environ['FLASK_ENV'] = 'production'
os.environ['SUPABASE_URL'] = ''
os.environ['SUPABASE_KEY'] = ''
os.environ['TRUSTED_PROXY_HOPS'] = '0'
os.environ['TRUSTED_PROTO_HOPS'] = '0'
os.environ['RENDER'] = 'false'

import app as module
from flask import Flask, request
from http_security import init_http_security

ROOT = Path(__file__).resolve().parents[1]


class SecurityTests(unittest.TestCase):
    def setUp(self):
        module.app.config.update(TESTING=True, FORCE_HTTPS=True)
        module.limiter.reset()
        module._MEMORIA_RECETAS.clear()
        self.client = module.app.test_client()

    def get(self, path, **kwargs):
        return self.client.get(path, base_url='https://localhost', **kwargs)

    def csrf_headers(self):
        page = self.get('/').get_data(as_text=True)
        token = re.search(r'name="csrf-token" content="([^"]+)"', page)[1]
        return {'X-CSRFToken': token, 'Referer': 'https://localhost/'}

    def post(self, path, payload=None, headers=None):
        return self.client.post(path, json=payload or {}, headers=headers or {},
                                base_url='https://localhost')

    def test_headers_on_pages_api_static_and_errors(self):
        for path in ['/', '/comparador', '/api/config', '/api/receta/historial',
                     '/static/js/auth.js', '/no-existe', '/static/no-existe.css']:
            with self.subTest(path=path):
                response = self.get(path)
                self.assertEqual(response.headers['X-Frame-Options'], 'DENY')
                self.assertEqual(response.headers['X-Content-Type-Options'], 'nosniff')
                self.assertEqual(response.headers['Strict-Transport-Security'], 'max-age=31536000')
                self.assertEqual(response.headers['Referrer-Policy'], 'no-referrer')
                csp = response.headers['Content-Security-Policy']
                self.assertIn("frame-ancestors 'none'", csp)
                self.assertIn("script-src 'self'", csp)
                self.assertNotIn('unsafe-inline', csp)
                self.assertNotIn('unsafe-eval', csp)
                if path != '/static/js/auth.js':
                    self.assertEqual(response.headers['Cache-Control'], 'no-store')
                response.close()

    def test_https_redirect_and_cookie(self):
        response = self.client.get('/')
        self.assertEqual(response.status_code, 308)
        self.assertEqual(response.headers['Location'], 'https://localhost/')
        self.assertNotIn('Strict-Transport-Security', response.headers)
        self.assertEqual(self.client.post('/api/auth/login', json={}).status_code, 400)
        cookie = self.get('/').headers['Set-Cookie']
        for flag in ['Secure', 'HttpOnly', 'SameSite=Lax']:
            self.assertIn(flag, cookie)

    def test_forwarded_header_not_trusted_by_default(self):
        response = self.client.get('/', headers={'X-Forwarded-Proto': 'https'})
        self.assertEqual(response.status_code, 308)

    def test_no_queries_or_get_search(self):
        for path in ['/api/auth/login?password=secret', '/api/buscar?producto=secret',
                     '/api/receta/historial?usuario_id=other']:
            response = self.get(path)
            self.assertEqual(response.status_code, 400)
            self.assertNotIn('secret', response.get_data(as_text=True))
            self.assertNotIn('Location', response.headers)
        self.assertEqual(self.get('/api/buscar').status_code, 405)

    def test_csrf_rejected_without_token_and_with_wrong_token(self):
        for headers in [{}, {'X-CSRFToken': 'invalid', 'Referer': 'https://localhost/'}]:
            response = self.post('/api/auth/login', headers=headers)
            self.assertEqual(response.status_code, 400)
            self.assertTrue(response.is_json)
            self.assertEqual(response.headers['Cache-Control'], 'no-store')

    def test_login_registration_and_session_minimize_data(self):
        headers = self.csrf_headers()
        user = {'id': 'alice', 'email': 'alice@example.test', 'last_sign_in_at': 1730000000,
                'identities': [{'internal': 'private'}]}
        data = {'user': user, 'access_token': 'fake-token', 'refresh_token': 'private-refresh'}
        with patch.object(module, '_supabase_configurado', return_value=True), \
             patch.object(module, 'auth_iniciar_sesion', return_value=data), \
             patch.object(module, 'auth_registrar', return_value=data), \
             patch.object(module, 'auth_obtener_usuario', return_value=user):
            for path in ['/api/auth/login', '/api/auth/registro']:
                response = self.post(path, {'email': user['email'], 'password': 'test-password'}, headers)
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.json['usuario'], {'id': 'alice', 'email': user['email']})
                self.assertNotIn('refresh_token', response.json)
                self.assertNotIn('1730000000', response.get_data(as_text=True))
            session = self.get('/api/auth/sesion', headers={'Authorization': 'Bearer fake-token'})
            self.assertTrue(session.json['autenticado'])
            self.assertEqual(set(session.json['usuario']), {'id', 'email'})

    def test_login_rate_limit_and_generic_error(self):
        headers = self.csrf_headers()
        with patch.object(module, '_supabase_configurado', return_value=True), \
             patch.object(module, 'auth_iniciar_sesion', side_effect=ValueError('internal-secret')):
            for _ in range(5):
                response = self.post('/api/auth/login', {'email': 'a@b.test', 'password': 'wrong'}, headers)
                self.assertEqual(response.status_code, 401)
                self.assertNotIn('internal-secret', response.get_data(as_text=True))
            response = self.post('/api/auth/login', {'email': 'a@b.test', 'password': 'wrong'}, headers)
            self.assertEqual(response.status_code, 429)
            self.assertIn('Content-Security-Policy', response.headers)
            self.assertEqual(response.headers['Cache-Control'], 'no-store')

    def test_search_and_recipe_authorization(self):
        headers = self.csrf_headers()
        self.assertEqual(self.post('/api/buscar', headers=headers).status_code, 401)
        self.assertEqual(self.get('/api/receta/historial').status_code, 401)
        headers['Authorization'] = 'Bearer fake-token'
        with patch.object(module, '_supabase_configurado', return_value=True), \
             patch.object(module, 'auth_obtener_usuario', return_value={'id': 'alice'}), \
             patch.object(module, 'buscar_en_farmacias', return_value=[]):
            response = self.post('/api/buscar', {'producto': 'paracetamol'}, headers)
            self.assertEqual(response.status_code, 200)
            self.assertTrue(response.json['resultados'])
            item = {'medicamento': 'Test', 'farmacia': 'Test', 'precio_unitario': 1, 'usuario_id': 'bob'}
            self.assertEqual(self.post('/api/receta/guardar', item, headers).status_code, 200)
            history = self.get('/api/receta/historial', headers=headers)
            self.assertEqual(history.json['data'][0]['usuario_id'], 'alice')

    def test_user_agent_does_not_bypass_authentication(self):
        for agent in ['Mozilla/5.0', 'Googlebot', 'sqlmap', '']:
            self.assertEqual(self.get('/api/receta/historial', headers={'User-Agent': agent}).status_code, 401)

    def test_cross_origin_post_is_rejected(self):
        headers = self.csrf_headers()
        headers['Referer'] = 'https://other.example/'
        self.assertEqual(self.post('/api/auth/login', headers=headers).status_code, 400)

    def test_logout_uses_csrf_and_calls_provider(self):
        headers = self.csrf_headers()
        headers['Authorization'] = 'Bearer fake-token'
        with patch.object(module, '_supabase_configurado', return_value=True), \
             patch.object(module, 'auth_cerrar_sesion') as logout:
            self.assertEqual(self.post('/api/auth/logout', headers=headers).status_code, 200)
            logout.assert_called_once_with('fake-token')

    def test_server_errors_keep_security_headers(self):
        with patch.dict(module.app.config, {'TESTING': False}), \
             patch.object(module, 'render_template', side_effect=RuntimeError('private-detail')), \
             patch.object(module.app, 'log_exception'):
            response = self.get('/')
            self.assertEqual(response.status_code, 500)
            self.assertNotIn('private-detail', response.get_data(as_text=True))
            self.assertEqual(response.headers['Cache-Control'], 'no-store')
            self.assertIn('Content-Security-Policy', response.headers)

    def test_rendered_assets_have_valid_integrity_and_no_inline_code(self):
        for path in ['/', '/comparador']:
            html = self.get(path).get_data(as_text=True)
            self.assertNotIn('<!--', html)
            self.assertNotRegex(html, r'<script\s*>')
            self.assertNotRegex(html, r'<(?:script|link)[^>]+(?:src|href)="https?://')
            for tag in re.findall(r'<(?:script|link)\b[^>]*>', html):
                asset = re.search(r'(?:src|href)="/static/([^"]+)"', tag)
                if asset:
                    integrity = re.search(r'integrity="([^"]+)"', tag)
                    self.assertIsNotNone(integrity)
                    actual = base64.b64encode(hashlib.sha384((ROOT / 'static' / asset[1]).read_bytes()).digest()).decode()
                    self.assertEqual(integrity[1], 'sha384-' + actual)

    def test_render_proxy_recognizes_https_without_trusting_client_ip(self):
        with patch.dict(os.environ, {'RENDER': 'true', 'TRUSTED_PROXY_HOPS': '0'}):
            os.environ.pop('TRUSTED_PROTO_HOPS', None)
            app = Flask('render-test', static_folder=str(ROOT / 'static'))
            init_http_security(app)

            @app.route('/')
            def home():
                return {'secure': request.is_secure, 'remote': request.remote_addr}

            response = app.test_client().get('/', headers={
                'X-Forwarded-Proto': 'http, https',
                'X-Forwarded-For': '192.0.2.12',
            })
            self.assertEqual(response.status_code, 200)
            self.assertTrue(response.json['secure'])
            self.assertEqual(response.json['remote'], '127.0.0.1')
            self.assertIn('Strict-Transport-Security', response.headers)

    def test_render_proxy_can_be_disabled_explicitly(self):
        with patch.dict(os.environ, {'RENDER': 'true', 'TRUSTED_PROXY_HOPS': '0',
                                    'TRUSTED_PROTO_HOPS': '0'}):
            app = Flask('render-disabled-test', static_folder=str(ROOT / 'static'))
            init_http_security(app)
            response = app.test_client().get('/', headers={'X-Forwarded-Proto': 'https'})
            self.assertEqual(response.status_code, 308)


if __name__ == '__main__':
    unittest.main()
