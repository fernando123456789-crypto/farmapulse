"""Política de reintentos y circuit breaker para llamadas HTTP salientes."""

import logging
import random
import time
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from threading import Lock
from urllib.parse import urlsplit

import requests

logger = logging.getLogger(__name__)

_RETRYABLE_STATUSES = {408, 425, 429, 500, 502, 503, 504}
_IDEMPOTENT_METHODS = {"GET", "HEAD", "OPTIONS"}


class CircuitOpenError(RuntimeError):
    """El circuito de un proveedor está abierto o ya tiene una prueba en curso."""

    def __init__(self, service, retry_after):
        super().__init__("El servicio externo está temporalmente no disponible")
        self.service = service
        self.retry_after = max(1, int(retry_after + 0.999))


class ResiliencePolicy:
    def __init__(self, max_attempts=3, base_delay=0.25, max_delay=2.0,
                 failure_threshold=5, reset_timeout=30, clock=None, sleep=None,
                 jitter=None):
        if max_attempts < 1 or failure_threshold < 1:
            raise ValueError("Los intentos y el umbral de fallos deben ser positivos")
        self.max_attempts = max_attempts
        self.base_delay = base_delay
        self.max_delay = max_delay
        self.failure_threshold = failure_threshold
        self.reset_timeout = reset_timeout
        self._clock = clock or time.monotonic
        self._sleep = sleep or time.sleep
        self._jitter = jitter or random.uniform
        self._lock = Lock()
        self._circuits = {}

    def request(self, method, url, send, **kwargs):
        method = method.upper()
        service = urlsplit(url).hostname or "servicio-externo"
        generation = self._acquire(service)
        retry_allowed = self._can_retry(method, kwargs.get("headers") or {})

        try:
            for attempt in range(self.max_attempts):
                try:
                    response = send()
                except (requests.Timeout, requests.ConnectionError) as error:
                    if retry_allowed and attempt + 1 < self.max_attempts:
                        self._sleep(self._retry_delay(attempt))
                        continue
                    self._record_failure(service, generation)
                    raise
                except requests.RequestException:
                    self._record_neutral(service, generation)
                    raise
                except Exception:
                    self._record_neutral(service, generation)
                    raise

                status = response.status_code
                is_failure = status == 408 or status >= 500
                should_retry = status in _RETRYABLE_STATUSES
                if should_retry and retry_allowed and attempt + 1 < self.max_attempts:
                    self._sleep(self._retry_delay(attempt, response.headers.get("Retry-After")))
                    continue
                if is_failure:
                    self._record_failure(service, generation)
                else:
                    self._record_success(service, generation)
                return response
        except Exception:
            raise

        raise RuntimeError("La política HTTP terminó sin respuesta")  # pragma: no cover

    @staticmethod
    def _can_retry(method, headers):
        if method in _IDEMPOTENT_METHODS:
            return True
        return any(str(name).lower() in {"idempotency-key", "x-idempotency-key"} and value
                   for name, value in headers.items())

    def _retry_delay(self, attempt, retry_after=None):
        cap = min(self.max_delay, self.base_delay * (2 ** attempt))
        server_delay = self._parse_retry_after(retry_after)
        if server_delay is not None:
            delay = min(self.max_delay, max(cap, server_delay))
            return delay + self._jitter(0, min(0.25, self.max_delay - delay))
        return self._jitter(0, cap)

    def _parse_retry_after(self, value):
        if not value:
            return None
        try:
            return min(self.max_delay, max(0.0, float(value)))
        except (TypeError, ValueError):
            try:
                momento = parsedate_to_datetime(value)
                if momento.tzinfo is None:
                    momento = momento.replace(tzinfo=timezone.utc)
                segundos = (momento - datetime.now(timezone.utc)).total_seconds()
                return min(self.max_delay, max(0.0, segundos))
            except (TypeError, ValueError, OverflowError):
                return None

    def _acquire(self, service):
        now = self._clock()
        with self._lock:
            circuit = self._circuits.setdefault(service, {
                "state": "closed", "failures": 0, "opened_at": 0.0,
                "probe_in_flight": False, "generation": 0,
            })
            if circuit["state"] == "open":
                remaining = self.reset_timeout - (now - circuit["opened_at"])
                if remaining > 0:
                    raise CircuitOpenError(service, remaining)
                circuit["state"] = "half_open"
                circuit["probe_in_flight"] = False
                circuit["generation"] += 1
                logger.info("circuit_breaker servicio=%s estado=half_open", service)
            if circuit["state"] == "half_open":
                if circuit["probe_in_flight"]:
                    raise CircuitOpenError(service, 1)
                circuit["probe_in_flight"] = True
            return circuit["generation"]

    def _record_success(self, service, generation):
        with self._lock:
            circuit = self._circuits[service]
            if circuit["generation"] != generation:
                return
            was_half_open = circuit["state"] == "half_open"
            circuit["state"] = "closed"
            circuit["failures"] = 0
            circuit["probe_in_flight"] = False
            if was_half_open:
                circuit["generation"] += 1
                logger.info("circuit_breaker servicio=%s estado=closed", service)

    def _record_neutral(self, service, generation):
        with self._lock:
            circuit = self._circuits[service]
            if circuit["generation"] == generation and circuit["state"] == "half_open":
                circuit["state"] = "closed"
                circuit["probe_in_flight"] = False
                circuit["failures"] = 0
                circuit["generation"] += 1

    def _record_failure(self, service, generation):
        with self._lock:
            circuit = self._circuits[service]
            if circuit["generation"] != generation:
                return
            circuit["failures"] += 1
            if circuit["state"] == "half_open" or circuit["failures"] >= self.failure_threshold:
                circuit["state"] = "open"
                circuit["opened_at"] = self._clock()
                circuit["probe_in_flight"] = False
                circuit["generation"] += 1
                logger.warning("circuit_breaker servicio=%s estado=open", service)

    def reset(self):
        """Limpia el estado de los circuitos; útil al aislar pruebas."""
        with self._lock:
            self._circuits.clear()
