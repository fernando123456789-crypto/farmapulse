"""Mido el rendimiento de FarmaPulse (latencia, percentiles y errores) sin dependencias externas.

Uso:
    python scripts/prueba_rendimiento.py --base-url https://farmapulse.onrender.com
    python scripts/prueba_rendimiento.py --base-url http://127.0.0.1:5055 --requests 100 --concurrency 5

Genera un informe en Markdown (--out) y un JSON con los datos crudos. Termina con código 1 si algún
endpoint supera su umbral de p95, para que GitHub Actions marque la corrida como fallida.
"""

import argparse
import json
import statistics
import sys
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

# (ruta, descripción, umbral p95 en segundos). La búsqueda consulta farmacias en vivo, por eso su umbral es mayor.
ENDPOINTS = [
    ("/healthz", "Comprobación de salud", 1.0),
    ("/", "Landing", 1.0),
    ("/comparador", "Comparador (vista)", 1.0),
    ("/api/config", "Configuración pública", 1.0),
    ("/api/ubicaciones", "Distritos", 1.0),
    ("/api/buscar?producto=paracetamol%20500mg", "Búsqueda de medicamento", 3.0),
]


def una_peticion(url, timeout):
    inicio = time.perf_counter()
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "FarmaPulse-Rendimiento/1.0"})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            r.read()
            codigo = r.status
    except urllib.error.HTTPError as e:
        codigo = e.code
    except Exception:
        codigo = 0
    return codigo, time.perf_counter() - inicio


def percentil(valores, p):
    orden = sorted(valores)
    k = max(0, min(len(orden) - 1, round(p / 100 * len(orden) + 0.5) - 1))
    return orden[k]


def medir(base, ruta, n, concurrencia, timeout):
    url = base.rstrip("/") + ruta
    with ThreadPoolExecutor(max_workers=concurrencia) as pool:
        resultados = list(pool.map(lambda _: una_peticion(url, timeout), range(n)))
    ok = [t for c, t in resultados if 200 <= c < 300]
    limitadas = sum(1 for c, _ in resultados if c == 429)
    errores = sum(1 for c, _ in resultados if c == 0 or c >= 500)
    tiempos = ok or [t for _, t in resultados]
    return {
        "ruta": ruta, "peticiones": n, "exitosas": len(ok), "limitadas_429": limitadas, "errores": errores,
        "media": statistics.mean(tiempos), "p50": percentil(tiempos, 50), "p95": percentil(tiempos, 95),
        "max": max(tiempos),
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base-url", required=True)
    ap.add_argument("--requests", type=int, default=50)
    ap.add_argument("--concurrency", type=int, default=5)
    ap.add_argument("--timeout", type=float, default=60.0)
    ap.add_argument("--out", default="informe_rendimiento.md")
    a = ap.parse_args()

    # Arranque en frío: en Render Free la primera petición puede tardar hasta ~50 s.
    _, frio = una_peticion(a.base_url.rstrip("/") + "/healthz", a.timeout)
    filas, falla = [], False
    for ruta, desc, umbral in ENDPOINTS:
        r = medir(a.base_url, ruta, a.requests, a.concurrency, a.timeout)
        r["descripcion"], r["umbral_p95"] = desc, umbral
        r["cumple"] = r["p95"] <= umbral and r["errores"] == 0
        falla |= not r["cumple"]
        filas.append(r)

    ahora = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    md = [f"# Informe de rendimiento de FarmaPulse", "",
          f"- Fecha: {ahora}", f"- URL: {a.base_url}",
          f"- Carga: {a.requests} peticiones por endpoint, {a.concurrency} en paralelo",
          f"- Primera petición (arranque en frío): {frio:.2f} s", "",
          "| Endpoint | Exitosas | 429 | Errores | Media (s) | p50 (s) | p95 (s) | Máx (s) | Umbral p95 (s) | Resultado |",
          "|---|---|---|---|---|---|---|---|---|---|"]
    for r in filas:
        md.append(f"| {r['ruta'].split('?')[0]} | {r['exitosas']}/{r['peticiones']} | {r['limitadas_429']} | {r['errores']} | "
                  f"{r['media']:.3f} | {r['p50']:.3f} | {r['p95']:.3f} | {r['max']:.3f} | {r['umbral_p95']:.1f} | "
                  f"{'Cumple' if r['cumple'] else 'No cumple'} |")
    with open(a.out, "w", encoding="utf-8") as f:
        f.write("\n".join(md) + "\n")
    with open(a.out.rsplit(".", 1)[0] + ".json", "w", encoding="utf-8") as f:
        json.dump({"fecha": ahora, "url": a.base_url, "arranque_frio": frio, "endpoints": filas}, f, indent=2)
    print("\n".join(md))
    sys.exit(1 if falla else 0)


if __name__ == "__main__":
    main()
