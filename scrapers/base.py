"""Interfaz común de consulta de productos."""

from __future__ import annotations

import time
from abc import ABC, abstractmethod
from datetime import datetime, timezone


class ScraperFarmacia(ABC):
    """Contrato + lógica compartida para un scraper de una farmacia."""

    nombre_farmacia: str = "Farmacia"
    url_base: str = ""

    cache_ttl_segundos: int = 15 * 60      # no repetir la misma búsqueda por 15 min
    intervalo_minimo_segundos: int = 3     # separación mínima entre peticiones reales

    def __init__(self):
        # Caché y rate-limit por INSTANCIA: así una farmacia con problemas
        # no bloquea a las demás (cada una tiene su propio reloj).
        self._cache: dict[str, tuple[float, list[dict]]] = {}
        self._ultima_peticion_real: float = 0.0

    # ------------------------------------------------------------------
    # Único método que cada farmacia debe implementar
    # ------------------------------------------------------------------
    @abstractmethod
    def _buscar_en_vivo(self, termino: str) -> list[dict]:
        """
        Devuelve los resultados reales de buscar `termino` en esta
        farmacia. Cada subclase decide CÓMO (API pública directa,
        Playwright, etc.) — ver _renderizar_con_playwright() si hace
        falta JavaScript. Forma esperada de cada dict:

            {
                "medicamento": str,
                "farmacia": str,                 # normalmente self.nombre_farmacia
                "precio_unitario": float,
                "precio_empaque": float | None,
                "presentacion": str,
                "tipo": "GENERICO" | "MARCA",
                "url_producto": str,
            }
        """
        raise NotImplementedError

    # ------------------------------------------------------------------
    # Lógica compartida (caché, rate-limit, manejo de errores)
    # ------------------------------------------------------------------
    def buscar(self, termino: str) -> list[dict]:
        """Punto de entrada público. Nunca lanza excepción: cualquier
        problema (timeout, endpoint caído, selector roto) se captura y
        se devuelve lista vacía, para que una farmacia con problemas no
        tumbe la búsqueda de las demás."""
        termino = (termino or "").strip()
        if not termino:
            return []

        if not self._cache_vencida(termino):
            return self._cache[termino][1]

        espera_restante = self.intervalo_minimo_segundos - (time.time() - self._ultima_peticion_real)
        if espera_restante > 0:
            entrada_previa = self._cache.get(termino)
            return entrada_previa[1] if entrada_previa else []

        try:
            resultados = self._buscar_en_vivo(termino)
        except Exception as exc:
            print(f"[FarmaPulse] {self.nombre_farmacia} no disponible ahora mismo "
                  f"({exc}). Se omite esta fuente para '{termino}'.")
            resultados = []

        for r in resultados:
            r.setdefault("farmacia", self.nombre_farmacia)
            r.setdefault("distrito", "")
            r.setdefault("dci", "")
            r.setdefault("laboratorio", self.nombre_farmacia)
            r.setdefault("consultado_en", datetime.now(timezone.utc).isoformat())

        self._ultima_peticion_real = time.time()
        self._cache[termino] = (time.time(), resultados)
        return resultados

    def _cache_vencida(self, termino: str) -> bool:
        entrada = self._cache.get(termino)
        if not entrada:
            return True
        guardado_en, _ = entrada
        return (time.time() - guardado_en) > self.cache_ttl_segundos

    # ------------------------------------------------------------------
    # Helper opcional para farmacias que SÍ necesitan renderizar JS
    # (ninguna llamada de red evasiva: mismo User-Agent normal que
    # cualquier navegador, solo para poder "ver" lo que ve un visitante).
    # ------------------------------------------------------------------
    @staticmethod
    def _renderizar_con_playwright(url: str, timeout_ms: int = 15000):
        """Devuelve una Page de Playwright con `url` ya cargada. El
        llamador es responsable de cerrar el navegador (usar dentro de
        un `with sync_playwright() as p:` propio, o ver ejemplo en
        scrapers/mifarma.py)."""
        from playwright.sync_api import sync_playwright

        p = sync_playwright().start()
        navegador = p.chromium.launch(headless=True)
        pagina = navegador.new_page(
            user_agent=("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) "
                        "Chrome/124.0.0.0 Safari/537.36"),
            locale="es-PE",
        )
        pagina.goto(url, timeout=timeout_ms, wait_until="networkidle")
        return p, navegador, pagina
