"""
FarmaPulse - scrapers/registry.py
"""

from concurrent.futures import ThreadPoolExecutor

from .farmaciauniversal import FarmaciaUniversalScraper
from .inkafarma import InkafarmaScraper
from .mifarma import MifarmaScraper

SCRAPERS_ACTIVOS = [
    InkafarmaScraper(),
    MifarmaScraper(),
    FarmaciaUniversalScraper(),
]


def nombres_farmacias_activas() -> list[str]:
    return [s.nombre_farmacia for s in SCRAPERS_ACTIVOS]


def buscar_en_farmacias(termino: str, farmacia_filtro: str | None = None) -> list[dict]:
    """
    Busca `termino` en todas las farmacias registradas en paralelo
    (o solo en la que coincida con `farmacia_filtro`).
    """
    seleccionados = [
        scraper for scraper in SCRAPERS_ACTIVOS
        if not (farmacia_filtro and farmacia_filtro.strip().lower() not in scraper.nombre_farmacia.lower())
    ]
    if len(seleccionados) <= 1:
        return seleccionados[0].buscar(termino) if seleccionados else []

    resultados: list[dict] = []
    with ThreadPoolExecutor(max_workers=len(seleccionados)) as pool:
        for items in pool.map(lambda s: s.buscar(termino), seleccionados):
            resultados.extend(items)
    return resultados