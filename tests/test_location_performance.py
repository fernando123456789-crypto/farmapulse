"""Compruebo capacidad de la ruta, mediciones y aislamiento entre usuarios."""

import unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from threading import Barrier
from unittest.mock import Mock, patch

import http_client
from test_identity_security import CheckoutIdentityFixture


class LocationPerformanceTests(CheckoutIdentityFixture, unittest.TestCase):
    body_location = {"direccion": "Dirección privada de prueba", "latitud": -12.107, "longitud": -76.999}

    def validar(self, headers=None, **changes):
        return self.client.post("/api/direcciones/validar", json={**self.body_location, **changes},
                                headers=self.headers if headers is None else headers)

    def test_100_requests_same_ip_keep_auth_and_do_not_hit_default_limits(self):
        self.module.limiter.reset()
        self.addCleanup(self.module.limiter.reset)
        with patch.object(self.module.limiter, "enabled", True):
            for index in range(100):
                response = self.validar()
                self.assertEqual(response.status_code, 200, f"Solicitud {index + 1}")
                self.assertEqual(response.json["distrito"], "San Borja")
        self.assertEqual(self.module.auth_obtener_usuario.call_count, 100)

    def test_suggestion_rate_limit_is_unchanged(self):
        self.module.limiter.reset()
        self.addCleanup(self.module.limiter.reset)
        with patch.object(self.module.limiter, "enabled", True):
            for _ in range(20):
                response = self.client.post("/api/direcciones/sugerencias", headers=self.headers,
                                            json={"texto": "Calle de prueba", "distrito": "Miraflores"})
                self.assertEqual(response.status_code, 400)
            self.assertEqual(self.client.post("/api/direcciones/sugerencias", headers=self.headers,
                                             json={"texto": "Calle de prueba"}).status_code, 429)

    def test_entry_exit_and_stage_times_do_not_expose_private_values(self):
        with self.assertLogs("request_timing", level="INFO") as log:
            response = self.validar()
        self.assertEqual(response.status_code, 200)
        entrada = datetime.fromisoformat(response.headers["X-Request-Started-At"].replace("Z", "+00:00"))
        salida = datetime.fromisoformat(response.headers["X-Request-Finished-At"].replace("Z", "+00:00"))
        self.assertLessEqual(entrada, salida)
        self.assertGreaterEqual(float(response.headers["X-Response-Time-Ms"]), 0)
        self.assertEqual(len(response.headers["X-Request-ID"]), 32)
        for etapa in ("total", "revocacion", "autenticacion", "bloqueo", "geometria"):
            self.assertIn(etapa + ";dur=", response.headers["Server-Timing"])
        for privado in (self.body_location["direccion"], self.user["email"], "Bearer test", "-12.107"):
            self.assertNotIn(privado, " ".join(log.output))
            self.assertNotIn(privado, str(response.headers))

    def test_invalid_input_and_missing_session_are_still_rejected_and_measured(self):
        self.assertEqual(self.validar(latitud=91).status_code, 400)
        response = self.validar(headers={})
        self.assertEqual(response.status_code, 401)
        self.assertIn("X-Request-Finished-At", response.headers)

    def test_revoked_session_and_blocked_account_cannot_use_the_route(self):
        self.module.identity_security.revoke_token("test")
        self.assertEqual(self.validar().status_code, 401)
        self.module.auth_obtener_usuario.assert_not_called()
        for _ in range(5):
            self.module.identity_security.record_failure({"correo": self.user["email"]})
        self.assertEqual(self.validar(headers={"Authorization": "Bearer other-token"}).status_code, 403)

    def test_unrelated_route_has_no_location_timing_headers(self):
        self.assertNotIn("X-Request-Started-At", self.client.get("/api/ubicaciones").headers)


class HTTPConnectionTests(unittest.TestCase):
    def test_reuses_connection_without_saving_tokens_or_cookies(self):
        session = Mock()
        client = http_client.ThreadLocalHTTP()
        with patch.object(http_client.requests, "Session", return_value=session) as factory:
            for token in ("first-user", "second-user"):
                client.request("GET", "https://example.supabase.co/auth/v1/user",
                               headers={"Authorization": "Bearer " + token}, timeout=8)
        factory.assert_called_once()
        self.assertEqual([call.kwargs["headers"]["Authorization"] for call in session.request.call_args_list],
                         ["Bearer first-user", "Bearer second-user"])
        self.assertEqual(session.cookies.clear.call_count, 2)
        session.headers.update.assert_not_called()

    def test_cookies_are_cleared_even_when_a_request_fails(self):
        session = Mock()
        session.request.side_effect = http_client.requests.ConnectionError()
        with patch.object(http_client.requests, "Session", return_value=session):
            with self.assertRaises(http_client.requests.ConnectionError):
                http_client.ThreadLocalHTTP().request("GET", "https://example.supabase.co")
        session.cookies.clear.assert_called_once()

    def test_parallel_threads_do_not_share_sessions(self):
        barrier = Barrier(4)
        client = http_client.ThreadLocalHTTP()
        def consultar(_):
            barrier.wait(timeout=10)
            client.request("GET", "https://example.supabase.co")
            first = client._local.session
            client.request("GET", "https://example.supabase.co")
            self.assertIs(first, client._local.session)
            return first
        with patch.object(http_client.requests, "Session", side_effect=lambda: Mock()):
            with ThreadPoolExecutor(max_workers=4) as pool:
                sessions = list(pool.map(consultar, range(4)))
        self.assertEqual(len({id(session) for session in sessions}), 4)
