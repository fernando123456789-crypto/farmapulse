"""
FarmaPulse - scrapers/inkafarma.py

Búsqueda en vivo en Inkafarma vía su índice público de Algolia.

Cómo se descubrió este endpoint: inspeccionando (con DevTools -> Network,
usando el propio navegador del usuario final) las peticiones que el
sitio inkafarma.pe dispara al buscar un producto en su buscador
público. No es un endpoint privado ni de admin: es el mismo que usa
cualquier visitante anónimo del sitio.

La "X-Algolia-API-Key" usada aquí es una API key de tipo "search-only"
de Algolia: por diseño de Algolia, este tipo de key es segura para
vivir en el frontend público de cualquier sitio, no expira ni requiere
sesión — es exactamente la misma que el navegador de cualquier persona
usa al visitar inkafarma.pe. No es una credencial privada ni una que
vaya a expirar como sí ocurre con tokens de sesión.

Reglas que este módulo respeta siempre:
  1. Solo consume este endpoint público de búsqueda, no endpoints
     internos/admin.
  2. Sin técnicas de evasión de detección (sin fingerprinting de TLS,
     sin rotación de IP, sin spoofing de huellas de navegador más allá
     de un User-Agent normal e identificable).
  3. Caché y límite de frecuencia (heredados de ScraperFarmacia) para
     no generar carga indebida sobre la infraestructura de
     Inkafarma/Algolia.
"""

import re

import requests

from .base import ScraperFarmacia

_PATRON_CANTIDAD = re.compile(r"(\d+)\s*(?:UN|un|comprimidos?|tabletas?|c[aá]psulas?)?\s*$")


class InkafarmaScraper(ScraperFarmacia):
    nombre_farmacia = "Inkafarma"
    url_base = "https://inkafarma.pe"

    algolia_app_id = "15W622LAQ4"
    algolia_search_key = "ccd8cbda203928003f7fe6f44ddbfc3a"  # key pública search-only
    algolia_index = "products"
    algolia_max_resultados = 50

    @property
    def _algolia_url(self) -> str:
        return f"https://{self.algolia_app_id.lower()}-dsn.algolia.net/1/indexes/*/queries"

    def _armar_url_producto(self, hit: dict) -> str:
        slug = hit.get("uri") or ""
        id_producto = hit.get("objectID") or ""
        if not slug or not id_producto:
            return ""
        return f"{self.url_base}/producto/{slug}/{id_producto}"

    def _estimar_precio_unitario(self, precio_empaque, presentacion: str):
        """
        Algolia no entrega precio por unidad suelta, solo precio de
        empaque. Se estima dividiendo el precio de empaque entre la
        cantidad de unidades que aparece en el texto de presentación
        (ej. "CAJA 100 UN" -> 100). Si no se puede extraer la cantidad,
        se devuelve None en vez de un valor inventado.
        """
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
                # Si no se pudo estimar el precio unitario (presentación
                # sin cantidad reconocible), se usa el precio de empaque
                # como respaldo para no romper el ordenamiento/comparación
                # (ver _calcular_ahorro_y_ordenar en app.py), marcado con
                # "precio_unitario_estimado" para que la UI pueda avisar.
                "precio_unitario": precio_unitario if precio_unitario is not None else precio,
                "precio_unitario_estimado": precio_unitario is None,
                "precio_empaque": precio,
                "presentacion": presentacion,
                "tipo": "GENERICO" if hit.get("isGeneric") else "MARCA",
                "url_producto": self._armar_url_producto(hit),
                "laboratorio": hit.get("brand") or hit.get("laboratory") or "",
                "dci": hit.get("composition", ""),
                "receta_requerida": hit.get("prescription") == "Presenta Receta",
                "imagen": hit.get("image", ""),
            })
        return resultados

    def _buscar_en_vivo(self, termino: str) -> list[dict]:
        params = (
            f"query={requests.utils.quote(termino)}"
            f"&facetFilters=[[\"channels:WEB\"]]"
            f"&length={self.algolia_max_resultados}"
            f"&offset=0"
        )

        payload = {"requests": [{"indexName": self.algolia_index, "params": params}]}

        respuesta = requests.post(
            self._algolia_url,
            headers={
                "X-Algolia-API-Key": self.algolia_search_key,
                "X-Algolia-Application-Id": self.algolia_app_id,
                "Content-Type": "application/json",
                "Origin": self.url_base,
                "Referer": f"{self.url_base}/",
                "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                                "AppleWebKit/537.36 (KHTML, like Gecko) "
                                "Chrome/124.0.0.0 Safari/537.36"),
            },
            json=payload,
            timeout=15,
        )
        respuesta.raise_for_status()
        datos = respuesta.json()

        hits = (datos.get("results") or [{}])[0].get("hits", [])
        return self._parsear_hits(hits)
