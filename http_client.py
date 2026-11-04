"""Reutilizo conexiones HTTP por hilo, sin conservar cookies ni credenciales."""

from threading import local

import requests


class ThreadLocalHTTP:
    def __init__(self):
        self._local = local()

    def request(self, method, url, **kwargs):
        session = getattr(self._local, "session", None)
        if session is None:
            session = self._local.session = requests.Session()
        try:
            # Los tokens y las claves se reciben en cada llamada, nunca en session.headers.
            return session.request(method, url, **kwargs)
        finally:
            session.cookies.clear()


http_client = ThreadLocalHTTP()
