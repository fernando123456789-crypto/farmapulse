"""Reutilizo conexiones HTTP por hilo, sin conservar cookies ni credenciales."""

from threading import local

import requests

from resilience import ResiliencePolicy


class ThreadLocalHTTP:
    def __init__(self, resilience=None):
        self._local = local()
        self.resilience = resilience or ResiliencePolicy()

    def request(self, method, url, **kwargs):
        return self.resilience.request(
            method, url, lambda: self._send(method, url, **kwargs), **kwargs,
        )

    def request_with_sender(self, method, url, sender, **kwargs):
        """Aplica resiliencia conservando un transporte alternativo, útil en desarrollo y pruebas."""
        return self.resilience.request(method, url, lambda: sender(url, **kwargs), **kwargs)

    def _send(self, method, url, **kwargs):
        session = getattr(self._local, "session", None)
        if session is None:
            session = self._local.session = requests.Session()
        try:
            # Los tokens y las claves se reciben en cada llamada, nunca en session.headers.
            return session.request(method, url, **kwargs)
        finally:
            session.cookies.clear()

    # Mantengo la misma interfaz mínima de ``requests`` para que los DAO puedan
    # reutilizar el pool sin conocer si están en producción o en pruebas.
    def get(self, url, **kwargs):
        return self.request("GET", url, **kwargs)

    def post(self, url, **kwargs):
        return self.request("POST", url, **kwargs)

    def put(self, url, **kwargs):
        return self.request("PUT", url, **kwargs)

    def delete(self, url, **kwargs):
        return self.request("DELETE", url, **kwargs)


http_client = ThreadLocalHTTP()
