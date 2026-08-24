"""
FarmaPulse - scrapers/registry.py

Registro central de farmacias activas. Para sumar una farmacia nueva:
    1. Crear scrapers/nueva_farmacia.py con una clase que herede de
       ScraperFarmacia (ver scrapers/base.py).
    2. Importarla e instanciarla en SCRAPERS_ACTIVOS más abajo.

Nada en app.py ni en los templates necesita tocarse: /api/buscar y la
tabla del comparador ya son dinámicos respecto a cuántas/qué farmacias
haya en esta lista.
"""

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
    Busca `termino` en todas las farmacias registradas (o solo en la que
    coincida con `farmacia_filtro`, si el usuario filtró por nombre).
    Cada scraper es independiente: si uno falla, no afecta a los demás.
    """
    resultados: list[dict] = []

    for scraper in SCRAPERS_ACTIVOS:
        if farmacia_filtro and farmacia_filtro.strip().lower() not in scraper.nombre_farmacia.lower():
            continue
        resultados.extend(scraper.buscar(termino))

    return resultados
