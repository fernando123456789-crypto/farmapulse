import json
import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import Mock, patch

import requests
from cryptography.fernet import InvalidToken

from identity_security import IdentitySecurity
from payment_ledger import PaymentLedger
from test_identity_security import CheckoutIdentityFixture


class SecurityApiTests(CheckoutIdentityFixture, unittest.TestCase):
    def setUp(self):
        self.real_auth_user = self.module.auth_obtener_usuario
        super().setUp()
        self.module.limiter.reset()
        self.addCleanup(self.module.limiter.reset)
        self.payment.return_value.status_code = 200
        self.payment.return_value.json.return_value = {}

    def test_five_logins_per_account_even_when_ip_changes(self):
        with patch.object(self.module.limiter, 'enabled', True):
            for index in range(6):
                response = self.client.post('/api/auth/login', json={
                    'email': 'Buyer@Example.com', 'password': 'incorrecta',
                }, environ_base={'REMOTE_ADDR': f'203.0.113.{index + 1}'})
                self.assertEqual(response.status_code, 502 if index < 5 else 429)
        self.assertEqual(self.payment.call_count, 5)

    def test_five_logins_per_ip_even_when_account_changes(self):
        with patch.object(self.module.limiter, 'enabled', True):
            for index in range(6):
                response = self.client.post('/api/auth/login', json={
                    'email': f'buyer{index}@example.com', 'password': 'incorrecta',
                })
                self.assertEqual(response.status_code, 502 if index < 5 else 429)
        self.assertEqual(self.payment.call_count, 5)

    def test_email_quota_is_shared_by_signup_resend_and_recovery(self):
        with patch.object(self.module.limiter, 'enabled', True):
            for index in range(5):
                result = self.client.post('/api/auth/registro', json={
                    'email': f'buyer{index}@example.com', 'password': 'ClaveSegura123!',
                })
                self.assertEqual(result.status_code, 200)
            for endpoint in ('reenviar-confirmacion', 'recuperar-contrasena', 'registro'):
                result = self.client.post(f'/api/auth/{endpoint}', json={
                    'email': 'other@example.com', 'password': 'ClaveSegura123!',
                })
                self.assertEqual(result.status_code, 429)
        self.assertEqual(self.payment.call_count, 5)

    def test_email_account_quota_cannot_be_bypassed_by_rotating_ip(self):
        with patch.object(self.module.limiter, 'enabled', True):
            for index in range(6):
                endpoint = ('registro', 'reenviar-confirmacion', 'recuperar-contrasena')[index % 3]
                result = self.client.post(f'/api/auth/{endpoint}', json={
                    'email': ' Buyer@Example.com ', 'password': 'ClaveSegura123!',
                }, environ_base={'REMOTE_ADDR': f'203.0.113.{index + 1}'})
                self.assertEqual(result.status_code, 200 if index < 5 else 429)
        self.assertEqual(self.payment.call_count, 5)

    def test_cross_origin_and_html_forms_never_reach_payment_or_auth(self):
        for endpoint in ('auth/login', 'checkout/pagar', 'receta/guardar'):
            for headers in ({'Origin': 'https://attacker.invalid'}, {'Sec-Fetch-Site': 'cross-site'}):
                response = self.client.post('/api/' + endpoint, json={}, headers=headers)
                self.assertEqual(response.status_code, 403)
        self.assertEqual(self.client.post('/api/auth/login', data={'email': 'x'}).status_code, 415)
        self.payment.assert_not_called()

    def test_body_limit_and_host_poisoning(self):
        response = self.client.post('/api/auth/registro', json={'email': 'x' * (129 * 1024)})
        self.assertEqual(response.status_code, 413)
        response = self.client.post('/api/auth/recuperar-contrasena',
                                    base_url='https://attacker.invalid', json={'email': 'buyer@example.com'})
        self.assertEqual(response.status_code, 400)
        self.payment.assert_not_called()

    def test_private_responses_are_not_cached_and_csp_limits_injection(self):
        response = self.client.get('/api/auth/sesion', headers=self.headers)
        self.assertIn('no-store', response.headers['Cache-Control'])
        self.assertEqual(response.headers['Referrer-Policy'], 'no-referrer')
        policy = response.headers['Content-Security-Policy']
        for rule in ("object-src 'none'", "base-uri 'self'", "frame-ancestors 'none'"):
            self.assertIn(rule, policy)
        self.assertNotIn("'unsafe-inline'", policy)

    def test_unconfirmed_anonymous_and_invalid_users_are_rejected(self):
        for user in ({}, {'id': 'buyer', 'email': 'b@example.com'},
                     {'id': 'buyer', 'email': 'b@example.com', 'email_confirmed_at': 'now', 'is_anonymous': True}):
            response = Mock(status_code=200)
            response.json.return_value = user
            with patch.object(self.module.requests, 'get', return_value=response), self.assertRaises(ValueError):
                self.real_auth_user('token')

    def test_recipe_uses_owner_token_and_never_client_owner(self):
        response = self.client.post('/api/receta/guardar', headers=self.headers, json={
            'usuario_id': 'someone-else', 'medicamento': 'Ibuprofeno', 'farmacia': 'Prueba', 'precio_unitario': 1,
        })
        self.assertEqual(response.status_code, 200)
        call = self.payment.call_args.kwargs
        self.assertEqual(call['headers']['Authorization'], 'Bearer test')
        self.assertEqual(call['json']['usuario_id'], self.user['id'])
        self.assertNotIn('someone-else', json.dumps(call))

    def test_history_is_scoped_to_owner_and_no_silent_fallback_on_failure(self):
        response = Mock()
        response.json.return_value = []
        with patch.object(self.module.requests, 'get', return_value=response) as get:
            result = self.client.get('/api/receta/historial', headers=self.headers)
        self.assertEqual(result.status_code, 200)
        self.assertEqual(get.call_args.kwargs['headers']['Authorization'], 'Bearer test')
        self.assertEqual(get.call_args.kwargs['params']['usuario_id'], 'eq.test-user')
        with patch.object(self.module.requests, 'get', side_effect=requests.ConnectionError):
            self.assertEqual(self.client.get('/api/receta/historial', headers=self.headers).status_code, 502)

    def test_bad_search_and_recipe_inputs_do_not_reach_external_services(self):
        with patch.object(self.module, 'buscar_en_farmacias') as search:
            for body in (['invalid'], {'producto': []}, {'producto': '<script>alert(1)</script>'},
                         {'producto': 'x' * 101}, {'producto': 'ibuprofeno', 'distrito': 'Cusco'}):
                self.assertEqual(self.client.post('/api/buscar', json=body).status_code, 400)
            search.assert_not_called()
        for price in ('NaN', 'Infinity', -1, True, {}, 7001):
            self.assertEqual(self.client.post('/api/receta/guardar', headers=self.headers, json={
                'medicamento': 'Prueba', 'farmacia': 'Prueba', 'precio_unitario': price,
            }).status_code, 400)

    def test_other_user_cannot_read_payment_state(self):
        self.module.payment_ledger.claim('private-order', 'token', '', 'other-user')
        result = self.client.get('/api/checkout/estado/private-order', headers=self.headers)
        self.assertEqual(result.status_code, 404)

    def test_logout_invalidates_token_even_if_provider_is_unavailable(self):
        with patch.object(self.module.requests, 'post', side_effect=requests.ConnectionError):
            self.assertEqual(self.client.post('/api/auth/logout', headers=self.headers).status_code, 200)
        self.assertTrue(self.module.identity_security.token_revoked('test'))
        self.assertEqual(self.client.get('/api/receta/historial', headers=self.headers).status_code, 401)
        self.assertFalse(self.client.get('/api/auth/sesion', headers=self.headers).json['autenticado'])


class StorageSecurityTests(unittest.TestCase):
    def test_encrypted_context_survives_restart_but_rejects_wrong_key(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'payments.sqlite3'
            ledger = PaymentLedger(path, 'secret')
            ledger.claim('order', 'token', '', 'owner')
            context = {'dni': '12345678', 'email': 'sensitive@example.invalid'}
            ledger.set_context('order', context)
            self.assertNotIn(b'sensitive@example.invalid', path.read_bytes())
            self.assertNotIn(b'12345678', path.read_bytes())
            self.assertEqual(PaymentLedger(path, 'secret').get('order', 'owner')['context'], context)
            with self.assertRaises(InvalidToken):
                PaymentLedger(path, 'different-secret').get('order')
            self.assertEqual(ledger.claim('order', 'token', '', 'other')[1], 409)

    def test_legacy_context_is_migrated_without_losing_receipt_data(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'payments.sqlite3'
            ledger = PaymentLedger(path, 'secret')
            ledger.claim('order', 'token', '', 'owner')
            context = {'email': 'legacy@example.invalid'}
            with closing(sqlite3.connect(path)) as db, db:
                db.execute('UPDATE payments SET context = ? WHERE order_id = ?', (json.dumps(context), 'order'))
            migrated = PaymentLedger(path, 'secret')
            self.assertEqual(migrated.get('order')['context'], context)
            with closing(sqlite3.connect(path)) as db:
                self.assertTrue(db.execute('SELECT context FROM payments').fetchone()[0].startswith('fernet:'))

    def test_sql_payload_is_only_data_and_does_not_escape_ownership(self):
        with tempfile.TemporaryDirectory() as directory:
            ledger = PaymentLedger(Path(directory) / 'payments.sqlite3', 'secret')
            payload = "'; DROP TABLE payments; --"
            ledger.claim(payload, 'token', '', 'owner')
            self.assertIsNotNone(ledger.get(payload, 'owner'))
            self.assertIsNone(ledger.get(payload, 'other'))
            store = IdentitySecurity(Path(directory) / 'security.sqlite3', 'secret')
            store.record_failure({'usuario': payload})
            self.assertEqual(store.status({'usuario': payload})['remaining'], 4)
            self.assertEqual(store.status({'usuario': 'other'})['remaining'], 5)
