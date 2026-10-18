"""Métricas del panel de administración a partir del registro real de pagos.

Reglas de negocio (explícitas):
- Solo las órdenes con estado ``approved`` cuentan como compras confirmadas e ingresos.
  ``pending``, ``processing``, ``unknown`` y ``rejected`` se muestran en la tabla, pero nunca suman ingresos.
- Cada orden es una fila única (``order_id`` es clave primaria), así que un pago no se cuenta dos veces.
- El ingreso de una orden es el total cobrado (productos + delivery), tal como se envió a Mercado Pago.
- Las fechas se interpretan en hora de Lima (UTC-5, sin horario de verano); la base guarda UTC.
"""

from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation

LIMA = timezone(timedelta(hours=-5))
ESTADOS = {"approved", "pending", "processing", "unknown", "rejected"}
ORDENES = {
    "fecha_desc", "fecha_asc", "producto_asc", "producto_desc",
    "cantidad_desc", "cantidad_asc", "importe_desc", "importe_asc",
}
POR_PAGINA_MAX = 100
MAX_DIAS_RELLENO = 366


class ParametrosInvalidos(ValueError):
    pass


def _decimal(valor):
    try:
        numero = Decimal(str(valor))
    except (InvalidOperation, ValueError):
        return Decimal("0")
    return numero if numero.is_finite() and numero >= 0 else Decimal("0")


def _fecha(valor, nombre):
    if not valor:
        return None
    try:
        return date.fromisoformat(valor)
    except (TypeError, ValueError):
        raise ParametrosInvalidos(f"La fecha «{nombre}» no es válida (usa AAAA-MM-DD)")


def rango_utc(desde, hasta):
    """Convierte fechas de Lima a límites UTC [inicio, fin) como texto de SQLite."""
    inicio = fin = None
    if desde:
        inicio = datetime(desde.year, desde.month, desde.day, tzinfo=LIMA).astimezone(timezone.utc)
    if hasta:
        siguiente = hasta + timedelta(days=1)
        fin = datetime(siguiente.year, siguiente.month, siguiente.day, tzinfo=LIMA).astimezone(timezone.utc)
    formato = "%Y-%m-%d %H:%M:%S"
    return (inicio.strftime(formato) if inicio else None, fin.strftime(formato) if fin else None)


def _a_lima(created_at):
    if not created_at:
        return None
    try:
        return datetime.strptime(created_at, "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc).astimezone(LIMA)
    except ValueError:
        return None


def leer_parametros(args):
    desde, hasta = _fecha(args.get("desde"), "desde"), _fecha(args.get("hasta"), "hasta")
    if desde and hasta and desde > hasta:
        raise ParametrosInvalidos("La fecha inicial no puede ser posterior a la final")
    estado = (args.get("estado") or "").strip().lower()
    if estado and estado not in ESTADOS:
        raise ParametrosInvalidos("El estado de pago no es válido")
    orden = args.get("orden") or "fecha_desc"
    if orden not in ORDENES:
        raise ParametrosInvalidos("El orden solicitado no es válido")
    try:
        pagina = max(1, int(args.get("pagina") or 1))
        por_pagina = min(POR_PAGINA_MAX, max(1, int(args.get("por_pagina") or 25)))
    except ValueError:
        raise ParametrosInvalidos("La paginación no es válida")
    q = " ".join((args.get("q") or "").split())[:100].casefold()
    return {"desde": desde, "hasta": hasta, "estado": estado, "orden": orden,
            "pagina": pagina, "por_pagina": por_pagina, "q": q}


def _normalizar(orden):
    lima = _a_lima(orden["created_at"])
    unidades = sum(p["cantidad"] for p in orden["productos"])
    return {
        "id": orden["id"],
        "fecha": lima.isoformat() if lima else None,
        "dia": lima.date().isoformat() if lima else None,
        "estado": orden["estado"],
        "cliente": orden["cliente"],
        "email": orden["email"],
        "productos": orden["productos"],
        "unidades": unidades,
        "subtotal": str(_decimal(orden["subtotal"]).quantize(Decimal("0.01"))),
        "delivery": str(_decimal(orden["delivery"]).quantize(Decimal("0.01"))),
        "total": str(_decimal(orden["total"]).quantize(Decimal("0.01"))),
        "legible": orden["legible"],
    }


def _coincide(orden, q):
    if not q:
        return True
    texto = " ".join([
        orden["id"], orden["email"], orden["cliente"],
        *(f"{p['nombre']} {p['presentacion']} {p['farmacia']}" for p in orden["productos"]),
    ]).casefold()
    return q in texto


def _clave_orden(orden):
    return {
        "fecha": lambda o: o["fecha"] or "",
        "producto": lambda o: min((p["nombre"].casefold() for p in o["productos"]), default=""),
        "cantidad": lambda o: o["unidades"],
        "importe": lambda o: Decimal(o["total"]),
    }[orden.split("_")[0]]


def construir_panel(ordenes_crudas, parametros):
    """Filtra, resume y pagina. ``ordenes_crudas`` ya viene acotado por fecha desde SQL."""
    filtro_fecha = bool(parametros["desde"] or parametros["hasta"])
    ordenes = []
    for cruda in ordenes_crudas:
        orden = _normalizar(cruda)
        if filtro_fecha and not orden["dia"]:
            continue  # sin fecha registrada: no se puede ubicar dentro de un rango
        if parametros["estado"] and orden["estado"] != parametros["estado"]:
            continue
        if not _coincide(orden, parametros["q"]):
            continue
        ordenes.append(orden)

    aprobadas = [o for o in ordenes if o["estado"] == "approved"]
    ingresos = sum((Decimal(o["total"]) for o in aprobadas), Decimal("0"))
    por_estado = defaultdict(int)
    for o in ordenes:
        por_estado[o["estado"]] += 1

    ingresos_dia, compras_dia = defaultdict(Decimal), defaultdict(int)
    productos = defaultdict(int)
    for o in aprobadas:
        if o["dia"]:
            ingresos_dia[o["dia"]] += Decimal(o["total"])
            compras_dia[o["dia"]] += 1
        for p in o["productos"]:
            productos[p["nombre"]] += p["cantidad"]

    dias = sorted(compras_dia)
    if dias and (date.fromisoformat(dias[-1]) - date.fromisoformat(dias[0])).days <= MAX_DIAS_RELLENO:
        actual, ultimo = date.fromisoformat(dias[0]), date.fromisoformat(dias[-1])
        dias = []
        while actual <= ultimo:
            dias.append(actual.isoformat())
            actual += timedelta(days=1)
    serie = [{"dia": d, "compras": compras_dia.get(d, 0), "ingresos": str(ingresos_dia.get(d, Decimal("0")).quantize(Decimal("0.01")))}
             for d in dias]

    top = sorted(productos.items(), key=lambda par: (-par[1], par[0].casefold()))[:8]
    ordenes.sort(key=_clave_orden(parametros["orden"]), reverse=parametros["orden"].endswith("_desc"))
    total_filas = len(ordenes)
    paginas = max(1, -(-total_filas // parametros["por_pagina"]))
    pagina = min(parametros["pagina"], paginas)
    inicio = (pagina - 1) * parametros["por_pagina"]

    return {
        "ok": True,
        "resumen": {
            "registros": len(ordenes),
            "compras_aprobadas": len(aprobadas),
            "unidades": sum(o["unidades"] for o in aprobadas),
            "ingresos": str(ingresos.quantize(Decimal("0.01"))),
            "ticket_promedio": str((ingresos / len(aprobadas)).quantize(Decimal("0.01")) if aprobadas else Decimal("0.00")),
            "por_estado": dict(por_estado),
            "sin_fecha": sum(1 for o in ordenes if not o["dia"]),
            "ilegibles": sum(1 for o in ordenes if not o["legible"]),
        },
        "serie": serie,
        "top_productos": [{"nombre": n, "unidades": u} for n, u in top],
        "compras": ordenes[inicio:inicio + parametros["por_pagina"]],
        "paginacion": {"pagina": pagina, "paginas": paginas, "por_pagina": parametros["por_pagina"], "total": total_filas},
    }
