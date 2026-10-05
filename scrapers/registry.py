"""Registro de proveedores de productos."""

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
