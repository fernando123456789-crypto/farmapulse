"""Pruebas deterministas de reintentos y circuit breaker HTTP."""

import unittest
from unittest.mock import Mock

import requests

from resilience import CircuitOpenError, ResiliencePolicy


class HTTPResilienceTests(unittest.TestCase):
    def respuesta(self, status):
        return Mock(status_code=status, headers={})

    def test_get_retries_timeouts_with_exponential_jitter(self):
        esperas = []
        policy = ResiliencePolicy(
            sleep=esperas.append, jitter=lambda minimo, maximo: maximo,
        )
        send = Mock(side_effect=[
            requests.Timeout(), requests.ConnectionError(), self.respuesta(200),
        ])

        result = policy.request("GET", "https://catalogo.example/api", send)

        self.assertEqual(result.status_code, 200)
        self.assertEqual(send.call_count, 3)
        self.assertEqual(esperas, [0.25, 0.5])

    def test_validation_and_non_idempotent_failures_are_not_retried(self):
        policy = ResiliencePolicy(sleep=Mock())
        invalid = Mock(return_value=self.respuesta(400))
        post = Mock(return_value=self.respuesta(503))

        policy.request("GET", "https://catalogo.example/api", invalid)
        policy.request("POST", "https://pagos.example/orders", post, json={"pago": True})

        invalid.assert_called_once()
        post.assert_called_once()

    def test_idempotency_key_allows_retrying_a_post(self):
        policy = ResiliencePolicy(sleep=Mock(), jitter=lambda minimo, maximo: 0)
        send = Mock(side_effect=[self.respuesta(503), self.respuesta(201)])

        result = policy.request(
            "POST", "https://pagos.example/orders", send,
            headers={"X-Idempotency-Key": "order-123"},
        )

        self.assertEqual(result.status_code, 201)
        self.assertEqual(send.call_count, 2)

    def test_retry_after_is_respected_within_the_configured_cap(self):
        wait = Mock()
        policy = ResiliencePolicy(sleep=wait, jitter=lambda minimo, maximo: maximo)
        limited = self.respuesta(429)
        limited.headers = {"Retry-After": "1"}
        send = Mock(side_effect=[limited, self.respuesta(200)])

        policy.request("GET", "https://catalogo.example/api", send)

        wait.assert_called_once_with(1.25)

    def test_open_circuit_rejects_calls_and_half_open_probe_recovers(self):
        now = [100.0]
        policy = ResiliencePolicy(
            max_attempts=1, failure_threshold=2, reset_timeout=10,
            clock=lambda: now[0], sleep=Mock(),
        )
        failing = Mock(return_value=self.respuesta(503))
        policy.request("GET", "https://photon.example/api", failing)
        policy.request("GET", "https://photon.example/api", failing)

        blocked = Mock(return_value=self.respuesta(200))
        with self.assertRaises(CircuitOpenError) as error:
            policy.request("GET", "https://photon.example/api", blocked)
        blocked.assert_not_called()
        self.assertEqual(error.exception.retry_after, 10)

        now[0] += 10
        recovered = Mock(return_value=self.respuesta(200))
        self.assertEqual(
            policy.request("GET", "https://photon.example/api", recovered).status_code, 200,
        )
        self.assertEqual(
            policy.request("GET", "https://photon.example/api", recovered).status_code, 200,
        )
        self.assertEqual(recovered.call_count, 2)

    def test_half_open_allows_only_one_probe(self):
        now = [0.0]
        policy = ResiliencePolicy(
            max_attempts=1, failure_threshold=1, reset_timeout=1,
            clock=lambda: now[0], sleep=Mock(),
        )
        policy.request("GET", "https://photon.example/api", Mock(return_value=self.respuesta(500)))
        now[0] = 1.0

        def probe():
            with self.assertRaises(CircuitOpenError):
                policy.request(
                    "GET", "https://photon.example/api",
                    Mock(return_value=self.respuesta(200)),
                )
            return self.respuesta(200)

        self.assertEqual(
            policy.request("GET", "https://photon.example/api", probe).status_code, 200,
        )


if __name__ == "__main__":
    unittest.main()
