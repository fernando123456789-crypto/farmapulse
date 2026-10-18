"""
FarmaPulse - scrapers/farmaciauniversal.py

Búsqueda en vivo en Farmacia Universal (farmaciauniversal.com), tienda
construida sobre VTEX (no Algolia, a diferencia de Inkafarma/Mifarma).

Cómo se descubrió: inspeccionando (DevTools -> Network -> Fetch/XHR) la
petición que el propio sitio dispara al renderizar la página de
resultados de búsqueda ("/panadol?_q=panadol&map=ft"). VTEX resuelve
esa página en el servidor consultando varias operaciones GraphQL
(productSearchV3, facetsV2, SearchMetadataV2) y devuelve TODO el
resultado ya resuelto en un solo JSON de "routing" — no hace falta
autenticarse ni conocer los hashes de las queries persistidas, solo
pedir esa misma URL de routing con Accept: application/json.

Formato de la respuesta: es el JSON que arma el propio Runtime de VTEX
para hidratar la página. Dentro de "queryData" viene una lista de 2-3
operaciones GraphQL ya resueltas; la que nos interesa es la que tiene
"productSearchV3" en su query — su campo "data" es, a su vez, un STRING
con el JSON de productSearch.products (doblemente serializado, típico
de VTEX).

Reglas que este módulo respeta siempre (idénticas a inkafarma.py /
mifarma.py):
  1. Solo consume este endpoint público de búsqueda (el mismo que arma
     cualquier visitante al cargar la página de resultados), no
     endpoints internos/admin.
  2. Sin técnicas de evasión de detección (sin fingerprinting de TLS,
     sin rotación de IP, sin spoofing de huellas de navegador más allá
     de un User-Agent normal e identificable).
  3. Caché y límite de frecuencia (heredados de ScraperFarmacia) para
     no generar carga indebida sobre la infraestructura de VTEX.

Nota de robustez: al ser un endpoint de "routing" pensado para
hidratar la página (no una API pública documentada como el catálogo
VTEX clásico), Farmacia Universal podría cambiar su formato con
actualizaciones del theme/runtime más seguido que una API de catálogo
estable. Si en algún momento este scraper empieza a devolver listas
vacías sin razón aparente, lo primero a revisar es si el índice de
"queryData" que contiene productSearchV3 cambió de posición, o si
apareció algún campo nuevo con el mismo propósito.
"""

import json
import re

import requests

from .base import ScraperFarmacia

_PATRON_CANTIDAD = re.compile(r"(\d+)\s*(?:UN|un|und|comprimidos?|tabletas?|c[aá]psulas?)?\s*$")


class FarmaciaUniversalScraper(ScraperFarmacia):
    nombre_farmacia = "Farmacia Universal"
    url_base = "https://www.farmaciauniversal.com"

    max_resultados = 50

    def _armar_url_producto(self, producto: dict) -> str:
        link = producto.get("link") or ""
        if not link:
            return ""
        return f"{self.url_base}{link}"

    @staticmethod
    def _obtener_especificacion(producto: dict, nombre_spec: str) -> str:
        """Busca un valor dentro de specificationGroups por nombre
        (ej. 'Presentación', 'Principio Activo'). VTEX repite estos
        valores en varios grupos ('Campos Auxiliares', 'allSpecifications'),
        con tomar el primero que aparezca alcanza."""
        for grupo in producto.get("specificationGroups") or []:
            for spec in grupo.get("specifications") or []:
                if spec.get("name") == nombre_spec:
                    valores = spec.get("values") or []
                    if valores:
                        return valores[0]
        return ""

    @staticmethod
    def _limpiar_html(texto: str) -> str:
        if not texto:
            return ""
        sin_tags = re.sub(r"<[^>]+>", " ", texto)
        return re.sub(r"\s+", " ", sin_tags).strip()

    def _mejor_oferta(self, producto: dict) -> dict | None:
        """Toma la oferta del primer seller del primer SKU (mismo
        criterio que usa la propia vitrina de VTEX para mostrar
        'el precio' del producto)."""
        items = producto.get("items") or []
        if not items:
            return None
        sellers = items[0].get("sellers") or []
        if not sellers:
            return None
        return sellers[0].get("commertialOffer")

    def _estimar_precio_unitario(self, precio_empaque, presentacion: str):
        """Mismo criterio que Inkafarma/Mifarma: Algolia/VTEX no separan
        precio por unidad suelta del precio de empaque, así que se
        estima con la cantidad detectada en el texto de presentación
        (ej. 'Sobre 2 und' -> 2). Si no se puede extraer, se devuelve
        None para no inventar un valor."""
        if not precio_empaque or not presentacion:
            return None
        match = _PATRON_CANTIDAD.search(presentacion.strip())
        if not match:
            return None
        cantidad = int(match.group(1))
        if cantidad <= 0:
            return None
        return round(precio_empaque / cantidad, 4)

    def _parsear_productos(self, productos_vtex: list[dict]) -> list[dict]:
        resultados = []
        for producto in productos_vtex:
            oferta = self._mejor_oferta(producto)
            if not oferta:
                continue  # sin seller/oferta disponible, no hay precio real que mostrar

            precio_empaque = oferta.get("Price")
            presentacion = self._obtener_especificacion(producto, "Presentación")
            precio_unitario = self._estimar_precio_unitario(precio_empaque, presentacion)

            requiere_receta = self._obtener_especificacion(
                producto, "Requiere receta médica"
            ).strip().lower() == "sí"

            principio_activo = self._obtener_especificacion(producto, "Principio Activo")
            dci = principio_activo or self._limpiar_html(producto.get("description", ""))

            items = producto.get("items") or []
            imagen = ""
            if items and items[0].get("images"):
                imagen = items[0]["images"][0].get("imageUrl", "")

            nombre = producto.get("productName", "")
            es_generico = "gen" in nombre.lower().split() or "genérico" in nombre.lower()

            resultados.append({
                "medicamento": nombre,
                "farmacia": self.nombre_farmacia,
                "precio_unitario": precio_unitario if precio_unitario is not None else precio_empaque,
                "precio_unitario_estimado": precio_unitario is None,
                "precio_empaque": precio_empaque,
                "presentacion": presentacion,
                "tipo": "GENERICO" if es_generico else "MARCA",
                "url_producto": self._armar_url_producto(producto),
                "laboratorio": producto.get("brand", ""),
                "dci": dci,
                "receta_requerida": requiere_receta,
                "imagen": imagen,
            })
        return resultados

    def _buscar_en_vivo(self, termino: str) -> list[dict]:
        # Misma URL de "routing" que arma el propio sitio al renderizar
        # la página de resultados (/{termino}?_q={termino}&map=ft) — VTEX
        # resuelve ahí mismo, en el servidor, las queries GraphQL que
        # arman la vitrina (productSearchV3, facetsV2, etc.) y entrega
        # todo ya resuelto en un solo JSON si se pide con
        # Accept: application/json.
        url = f"{self.url_base}/{termino}"
        params = {
            "_q": termino,
            "map": "ft",
            "__pickRuntime": (
                "appsEtag,blocks,blocksTree,components,contentMap,extensions,"
                "messages,page,pages,query,queryData,route,runtimeMeta,settings"
            ),
            "__device": "tablet",
        }

        respuesta = requests.get(
            url,
            params=params,
            headers={
                "Accept": "application/json",
                "Referer": f"{self.url_base}/{termino}?_q={termino}&map=ft",
                "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                                "AppleWebKit/537.36 (KHTML, like Gecko) "
                                "Chrome/124.0.0.0 Safari/537.36"),
            },
            timeout=15,
        )
        respuesta.raise_for_status()
        datos = respuesta.json()

        for entrada in datos.get("queryData") or []:
            if "productSearch(" not in (entrada.get("query") or ""):
                continue
            data_str = entrada.get("data")
            if not data_str:
                continue
            data_resuelta = json.loads(data_str)
            productos = (data_resuelta.get("productSearch") or {}).get("products") or []
            return self._parsear_productos(productos[: self.max_resultados])

        return []
