"""Mido la validación de direcciones sin registrar direcciones ni sesiones."""

import logging
from contextlib import contextmanager
from datetime import datetime, timezone
from time import perf_counter
from uuid import uuid4

from flask import g, has_request_context, request
from flask.logging import default_handler

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)
if not logger.handlers:
    logger.addHandler(default_handler)
logger.propagate = False


def _utc():
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def register_location_timing(app):
    @app.before_request
    def start_location_timing():
        if request.endpoint == "api_validar_direccion":
            g.location_timing = {
                "id": uuid4().hex, "entrada": _utc(), "inicio": perf_counter(), "etapas": {},
            }
            logger.info("ubicacion entrada id=%s hora_utc=%s",
                        g.location_timing["id"], g.location_timing["entrada"])

    @app.after_request
    def finish_location_timing(response):
        timing = getattr(g, "location_timing", None)
        if timing is None:
            return response
        total = (perf_counter() - timing["inicio"]) * 1000
        salida = _utc()
        etapas = timing["etapas"]
        response.headers["X-Request-ID"] = timing["id"]
        response.headers["X-Request-Started-At"] = timing["entrada"]
        response.headers["X-Request-Finished-At"] = salida
        response.headers["X-Response-Time-Ms"] = f"{total:.3f}"
        response.headers["Server-Timing"] = ", ".join([
            f"total;dur={total:.3f}",
            *(f"{nombre};dur={ms:.3f}" for nombre, ms in etapas.items()),
        ])
        logger.info("ubicacion salida id=%s hora_utc=%s estado=%s total_ms=%.3f etapas_ms=%s",
                    timing["id"], salida, response.status_code, total,
                    {nombre: round(ms, 3) for nombre, ms in etapas.items()})
        return response


@contextmanager
def measure_stage(name):
    timing = getattr(g, "location_timing", None) if has_request_context() else None
    if timing is None:
        yield
        return
    inicio = perf_counter()
    try:
        yield
    finally:
        etapas = timing["etapas"]
        etapas[name] = etapas.get(name, 0) + (perf_counter() - inicio) * 1000
