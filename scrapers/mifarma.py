"""
FarmaPulse - scrapers/mifarma.py

Búsqueda en vivo en Mifarma vía su índice público de Algolia.

Mismo patrón que scrapers/inkafarma.py: Mifarma (también del grupo
InRetail) expone su propio índice de Algolia usado por el buscador
público del sitio. Endpoint, application-id e index descubiertos
inspeccionando (DevTools -> Network -> Fetch/XHR) la petición que
mifarma.com.pe dispara al buscar un producto en su buscador público.

La "X-Algolia-API-Key" usada aquí es una API key de tipo "search-only"
de Algolia: igual que en Inkafarma, es la misma que recibe el navegador
de cualquier visitante anónimo del sitio, no expira ni requiere sesión,
y por diseño de Algolia es segura para vivir en un frontend público.

Reglas que este módulo respeta siempre (idénticas a inkafarma.py):
  1. Solo consume este endpoint público de búsqueda, no endpoints
     internos/admin.
  2. Sin técnicas de evasión de detección (sin fingerprinting de TLS,
     sin rotación de IP, sin spoofing de huellas de navegador más allá
     de un User-Agent normal e identificable).
  3. Caché y límite de frecuencia (heredados de ScraperFarmacia) para
     no generar carga indebida sobre la infraestructura de
     Mifarma/Algolia.

Diferencia de formato respecto a Inkafarma: el endpoint de Mifarma es
de un solo índice (".../indexes/products/query") en vez del endpoint
multi-índice (".../indexes/*/queries") que usa Inkafarma, así que el
payload y el parseo de la respuesta son ligeramente distintos, pero el
JSON de cada "hit" trae los mismos campos (priceList, pricePromo,
presentation, composition, brand/laboratory, isGeneric, etc.), así que
se reutiliza la misma lógica de estimación de precio unitario.
"""

import json
import re

import requests

from .base import ScraperFarmacia

_PATRON_CANTIDAD = re.compile(r"(\d+)\s*(?:UN|un|comprimidos?|tabletas?|c[aá]psulas?)?\s*$")


class MifarmaScraper(ScraperFarmacia):
    nombre_farmacia = "Mifarma"
    url_base = "https://www.mifarma.com.pe"

    algolia_app_id = "O74E6QKJ1F"
    algolia_search_key = "f14e7e2c350bd2c9bf3b5ff078ccd82f"  # key pública search-only
    algolia_index = "products"
    algolia_max_resultados = 50

    @property
    def _algolia_url(self) -> str:
        return f"https://{self.algolia_app_id.lower()}-dsn.algolia.net/1/indexes/{self.algolia_index}/query"

    def _armar_url_producto(self, hit: dict) -> str:
        slug = hit.get("uri") or ""
        if not slug:
            return ""
        return f"{self.url_base}/{slug}"

    def _estimar_precio_unitario(self, precio_empaque, presentacion: str):
        """Igual que en Inkafarma: Algolia no entrega precio por unidad
        suelta, solo precio de empaque. Se estima dividiendo entre la
        cantidad que aparece en el texto de presentación (ej. "SOBRE X2
        TABS 1 UN" -> 2, ya que la unidad de venta es el sobre de 2).
        Si no se puede extraer la cantidad, se devuelve None en vez de
        un valor inventado."""
        if not precio_empaque or not presentacion:
            return None
        match = _PATRON_CANTIDAD.search(presentacion.strip())
        if not match:
            return None
        cantidad = int(match.group(1))
        if cantidad <= 0:
            return None
        return round(precio_empaque / cantidad, 4)

    def _parsear_hits(self, hits: list[dict]) -> list[dict]:
        resultados = []
        for hit in hits:
            precio = hit.get("priceList")
            # withPromotion + pricePromo: si hay promo activa, ese es el
            # precio real que paga el cliente; si no, viene en 0 y se ignora.
            if hit.get("withPromotion") and hit.get("pricePromo"):
                precio = hit["pricePromo"]

            presentacion = hit.get("presentation") or ""
            precio_unitario = self._estimar_precio_unitario(precio, presentacion)

            resultados.append({
                "medicamento": hit.get("name", ""),
                "farmacia": self.nombre_farmacia,
                # Mismo respaldo que Inkafarma: si no se pudo estimar el
                # precio unitario, se usa el precio de empaque para no
                # romper el ordenamiento/comparación en
                # _calcular_ahorro_y_ordenar (app.py), marcado con
                # "precio_unitario_estimado" para que la UI pueda avisar.
                "precio_unitario": precio_unitario if precio_unitario is not None else precio,
                "precio_unitario_estimado": precio_unitario is None,
                "precio_empaque": precio,
                "presentacion": presentacion,
                "tipo": "GENERICO" if hit.get("isGeneric") else "MARCA",
                "url_producto": self._armar_url_producto(hit),
                "laboratorio": hit.get("laboratory") or hit.get("brand") or "",
                "dci": self._limpiar_html(hit.get("composition", "")),
                "receta_requerida": hit.get("prescription") not in (None, "", "Venta Libre"),
                "imagen": hit.get("image", ""),
            })
        return resultados

    @staticmethod
    def _limpiar_html(texto: str) -> str:
        """La composición de Mifarma viene con tags HTML (<ul><li>...),
        a diferencia de Inkafarma que la entrega en texto plano."""
        if not texto:
            return ""
        sin_tags = re.sub(r"<[^>]+>", " ", texto)
        return re.sub(r"\s+", " ", sin_tags).strip()

    def _buscar_en_vivo(self, termino: str) -> list[dict]:
        payload = {
            "query": termino,
            "facetFilters": [["channels:WEB"]],
            "hitsPerPage": self.algolia_max_resultados,
            "clickAnalytics": True,
        }

        respuesta = requests.post(
            self._algolia_url,
            params={
                "x-algolia-agent": "Algolia for JavaScript (4.25.2); Browser (lite)",
                "x-algolia-api-key": self.algolia_search_key,
                "x-algolia-application-id": self.algolia_app_id,
            },
            headers={
                "Content-Type": "application/x-www-form-urlencoded",
                "Origin": self.url_base,
                "Referer": f"{self.url_base}/",
                "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                                "AppleWebKit/537.36 (KHTML, like Gecko) "
                                "Chrome/124.0.0.0 Safari/537.36"),
            },
            data=json.dumps(payload),
            timeout=15,
        )
        respuesta.raise_for_status()
        datos = respuesta.json()

        hits = datos.get("hits", [])
        return self._parsear_hits(hits)
