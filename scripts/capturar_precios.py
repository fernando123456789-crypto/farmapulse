"""
FarmaPulse - scripts/capturar_precios.py
-----------------------------------------
Script independiente de app.py. Se ejecuta una vez por noche (vía
GitHub Actions, ver .github/workflows/capturar_precios.yml) y hace:

  1. Lee la watchlist desde la tabla `medicamentos` de Supabase.
  2. Para cada medicamento, busca en las 3 farmacias registradas en
     scrapers/registry.py (misma función que usa el comparador web).
  3. Guarda cada resultado como una fila NUEVA en `precios` (nunca
     sobrescribe — así se construye el histórico).
  4. Registra en `scrapes_log` si cada farmacia respondió o no, para
     poder distinguir después "no había oferta" de "el scraper falló".

Uso local (para probarlo antes de programarlo):
    pip install -r requirements.txt
    playwright install chromium
    python scripts/capturar_precios.py

En producción lo dispara GitHub Actions, no se corre a mano.

. /test de push
"""

from __future__ import annotations

import os
import sys
import time
from datetime import datetime, timezone

from dotenv import load_dotenv

# Permite correr el script desde la raíz del proyecto o desde /scripts
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scrapers.registry import SCRAPERS_ACTIVOS, buscar_en_farmacias  # noqa: E402
from dao.captura_precios_dao import CapturaPreciosDAO  # noqa: E402

# ---------------------------------------------------------------------------
# Configuración
# ---------------------------------------------------------------------------
load_dotenv()

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")

# Pausa entre productos para no saturar las farmacias con peticiones
# seguidas (además del rate-limit propio que ya tiene cada scraper).
PAUSA_ENTRE_PRODUCTOS_SEGUNDOS = 3

if not SUPABASE_URL or not SUPABASE_KEY or "tu-proyecto" in SUPABASE_URL:
    print("[capturar_precios] ERROR: SUPABASE_URL / SUPABASE_KEY no configurados. "
          "Este script necesita Supabase real, no tiene modo degradado.")
    sys.exit(1)

from supabase import create_client  # noqa: E402

supabase = create_client(SUPABASE_URL, SUPABASE_KEY)
captura_dao = CapturaPreciosDAO(supabase)


def capturar_precios_de_medicamento(medicamento: dict, nombres_farmacias: list[str]) -> tuple[int, int]:
    """Busca un medicamento en las 3 farmacias, guarda precios y log.
    Devuelve (precios_insertados, farmacias_sin_resultado)."""
    medicamento_id = medicamento["id"]
    termino = medicamento["nombre"]

    try:
        resultados = buscar_en_farmacias(termino)
    except Exception as exc:  # nunca debe tumbar todo el script
        print(f"  [ERROR] '{termino}': {exc}")
        resultados = []
        for nombre_farmacia in nombres_farmacias:
            _registrar_log(medicamento_id, nombre_farmacia, encontrado=False,
                           cantidad=0, error=str(exc))
        return 0, len(nombres_farmacias)

    precios_insertados = 0
    farmacias_sin_resultado = 0

    for nombre_farmacia in nombres_farmacias:
        items_de_esta_farmacia = [r for r in resultados if r.get("farmacia") == nombre_farmacia]

        if not items_de_esta_farmacia:
            farmacias_sin_resultado += 1
            _registrar_log(medicamento_id, nombre_farmacia, encontrado=False, cantidad=0)
            continue

        farmacia_id = captura_dao.obtener_o_crear_farmacia_id(nombre_farmacia)

        for item in items_de_esta_farmacia:
            fila = {
                "medicamento_id": medicamento_id,
                "farmacia_id": farmacia_id,
                "distrito_id": None,  # los scrapers hoy no devuelven precio por distrito
                "presentacion_id": captura_dao.obtener_o_crear_presentacion_id(item.get("presentacion", "")),
                "precio_unitario": item.get("precio_unitario"),
                "precio_empaque": item.get("precio_empaque"),
                "fuente": "scraper",
                "consultado_en": datetime.now(timezone.utc).isoformat(),
            }
            captura_dao.insertar_precio(fila)
            precios_insertados += 1

        _registrar_log(medicamento_id, nombre_farmacia, encontrado=True,
                   cantidad=len(items_de_esta_farmacia))

    return precios_insertados, farmacias_sin_resultado


def _registrar_log(medicamento_id: str, nombre_farmacia: str, encontrado: bool,
                    cantidad: int, error: str | None = None) -> None:
    farmacia_id = captura_dao.obtener_o_crear_farmacia_id(nombre_farmacia)
    captura_dao.registrar_scrape({
        "farmacia_id": farmacia_id,
        "medicamento_id": medicamento_id,
        "encontrado": encontrado,
        "cantidad_resultados": cantidad,
        "error": error,
        "ejecutado_en": datetime.now(timezone.utc).isoformat(),
    })


def main() -> None:
    nombres_farmacias = [s.nombre_farmacia for s in SCRAPERS_ACTIVOS]
    watchlist = captura_dao.obtener_watchlist()

    if not watchlist:
        print("[capturar_precios] La tabla 'medicamentos' está vacía. "
              "Corre antes sql/03_watchlist_medicamentos.sql en Supabase.")
        sys.exit(1)

    print(f"[capturar_precios] Iniciando captura de {len(watchlist)} productos "
          f"en {len(nombres_farmacias)} farmacias: {', '.join(nombres_farmacias)}")

    total_precios = 0
    total_fallos = 0

    for i, medicamento in enumerate(watchlist, start=1):
        print(f"[{i}/{len(watchlist)}] {medicamento['nombre']}...")
        insertados, fallos = capturar_precios_de_medicamento(medicamento, nombres_farmacias)
        total_precios += insertados
        total_fallos += fallos
        time.sleep(PAUSA_ENTRE_PRODUCTOS_SEGUNDOS)

    print(f"[capturar_precios] Listo. Precios guardados: {total_precios}. "
          f"Farmacia+producto sin resultado: {total_fallos}.")


if __name__ == "__main__":
    main()
