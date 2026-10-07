"""
FarmaPulse - Servidor Flask
----------------------------
Red compartida para medicamentos de confianza.

Este servidor expone:
  - Vistas HTML (landing y comparador)
  - API `/api/buscar` que consulta en vivo las farmacias registradas en
    scrapers/registry.py (Inkafarma, Mifarma, ...). Agregar una farmacia
    nueva no requiere tocar este archivo — ver scrapers/base.py.
  - Autenticación con Supabase Auth (correo + contraseña).
  - Botón de WhatsApp configurable.
  - Algoritmo de ordenamiento/ahorro por precio unitario.
  - Integración con Supabase para guardar/consultar "listas de receta".

Ejecutar:
    pip install -r requirements.txt
    playwright install chromium   # una sola vez
    python app.py
Luego abrir http://127.0.0.1:5000
"""

import os
import random
import uuid
from datetime import datetime, timezone
from functools import wraps

import requests
from dotenv import load_dotenv
from flask import Flask, g, jsonify, render_template, request
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from flask_talisman import Talisman

from scrapers.registry import buscar_en_farmacias, nombres_farmacias_activas
from flask_wtf.csrf import CSRFProtect

# ---------------------------------------------------------------------------
# Configuración inicial
# ---------------------------------------------------------------------------
load_dotenv()

app = Flask(__name__)
csrf = CSRFProtect(app)

# Validar que SECRET_KEY esté configurada en .env (nunca usar default inseguro en producción)
SECRET_KEY = os.getenv("SECRET_KEY")
if not SECRET_KEY:
    raise ValueError(
        "❌ ERROR CRÍTICO: SECRET_KEY no está configurada.\n"
        "Por favor, configura SECRET_KEY en tu archivo .env\n"
        "Ejemplo: SECRET_KEY=<clave-segura-de-32-caracteres>"
    )
app.config["SECRET_KEY"] = SECRET_KEY

# =========================================================================
# Seguridad: Rate limiting contra fuerza bruta en autenticación
# =========================================================================
limiter = Limiter(
    app=app,
    key_func=get_remote_address,
    default_limits=["200 per day", "50 per hour"]
)

# =========================================================================
# Seguridad: Cabeceras HTTP obligatorias contra CSRF, XSS, clickjacking
# =========================================================================
Talisman(
    app,
    force_https=False,  # En desarrollo. En producción cambiar a True
    strict_transport_security=True,
    strict_transport_security_max_age=31536000,
    content_security_policy={
        "default-src": "'self'",
        "script-src": ["'self'", "cdn.jsdelivr.net", "cdnjs.cloudflare.com", "kit.fontawesome.com"],
        "style-src": ["'self'", "cdn.jsdelivr.net", "cdnjs.cloudflare.com", "fonts.googleapis.com"],
        "img-src": ["'self'", "data:", "https:"],
        "font-src": ["'self'", "fonts.gstatic.com", "cdnjs.cloudflare.com"],
    }
)

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")

WHATSAPP_NUMERO = os.getenv("WHATSAPP_NUMERO", "51963119803")

# ---------------------------------------------------------------------------
# Cliente Supabase (con manejo de errores si las credenciales no son válidas
# o si el paquete no puede inicializar la conexión — la app debe seguir
# funcionando en modo "solo comparador" aunque Supabase falle).
# ---------------------------------------------------------------------------
supabase_client = None
try:
    from supabase import create_client

    if SUPABASE_URL and SUPABASE_KEY and "tu-proyecto" not in SUPABASE_URL:
        supabase_client = create_client(SUPABASE_URL, SUPABASE_KEY)
        print("[FarmaPulse] Conexión a Supabase inicializada correctamente.")
    else:
        print("[FarmaPulse] Supabase no configurado (usando valores de ejemplo en .env). "
              "Las rutas /api/receta funcionarán en modo degradado (memoria local).")
except Exception as exc:  # pragma: no cover
    print(f"[FarmaPulse] No se pudo inicializar Supabase: {exc}")
    supabase_client = None

# Almacenamiento en memoria como fallback si Supabase no está disponible
# (permite probar la app end-to-end sin credenciales reales).
_MEMORIA_RECETAS = []

# ---------------------------------------------------------------------------
# Autenticación (Supabase Auth) — correo + contraseña, "lo clásico"
# ---------------------------------------------------------------------------
# Se llama directo a la REST API de Supabase Auth (no al cliente Python
# global de arriba) porque ese cliente se comparte entre TODAS las
# peticiones del servidor Flask; guardar ahí la sesión de un usuario la
# mezclaría con la de otro usuario concurrente. Con la REST API cada
# petición lleva su propio token: es el patrón correcto para un backend
# multiusuario.
AUTH_TIMEOUT = 8


def _auth_url(ruta: str) -> str:
    return f"{SUPABASE_URL.rstrip('/')}/auth/v1{ruta}"


def _auth_headers(access_token: str | None = None) -> dict:
    headers = {"apikey": SUPABASE_KEY, "Content-Type": "application/json"}
    if access_token:
        headers["Authorization"] = f"Bearer {access_token}"
    return headers


def _supabase_configurado() -> bool:
    return bool(SUPABASE_URL and SUPABASE_KEY and "tu-proyecto" not in SUPABASE_URL)


def auth_registrar(email: str, password: str) -> dict:
    respuesta = requests.post(
        _auth_url("/signup"), headers=_auth_headers(),
        json={"email": email, "password": password}, timeout=AUTH_TIMEOUT,
    )
    datos = respuesta.json()
    if respuesta.status_code >= 400:
        raise ValueError(datos.get("msg") or datos.get("error_description") or "No se pudo registrar la cuenta")
    return datos


def auth_iniciar_sesion(email: str, password: str) -> dict:
    respuesta = requests.post(
        _auth_url("/token?grant_type=password"), headers=_auth_headers(),
        json={"email": email, "password": password}, timeout=AUTH_TIMEOUT,
    )
    datos = respuesta.json()
    if respuesta.status_code >= 400:
        raise ValueError(datos.get("error_description") or datos.get("msg") or "Credenciales inválidas")
    return datos


def auth_cerrar_sesion(access_token: str) -> None:
    requests.post(_auth_url("/logout"), headers=_auth_headers(access_token), timeout=AUTH_TIMEOUT)


def auth_obtener_usuario(access_token: str) -> dict:
    respuesta = requests.get(_auth_url("/user"), headers=_auth_headers(access_token), timeout=AUTH_TIMEOUT)
    if respuesta.status_code >= 400:
        raise ValueError("Sesión inválida o expirada")
    return respuesta.json()


def sesion_opcional(f):
    """Adjunta g.usuario si hay un Bearer token válido. Nunca bloquea la
    petición: sin token (o inválido), la ruta sigue en modo invitado."""
    @wraps(f)
    def envoltura(*args, **kwargs):
        g.usuario = None
        auth_header = request.headers.get("Authorization", "")
        if auth_header.startswith("Bearer ") and _supabase_configurado():
            token = auth_header.removeprefix("Bearer ").strip()
            try:
                g.usuario = auth_obtener_usuario(token)
            except Exception:
                g.usuario = None
        return f(*args, **kwargs)
    return envoltura


def sesion_requerida(f):
    """Igual que sesion_opcional, pero BLOQUEA la petición si no hay un
    Bearer token válido. Se usa en las rutas que ahora exigen login
    (buscar, guardar receta, ver historial)."""
    @wraps(f)
    def envoltura(*args, **kwargs):
        g.usuario = None
        auth_header = request.headers.get("Authorization", "")
        if auth_header.startswith("Bearer ") and _supabase_configurado():
            token = auth_header.removeprefix("Bearer ").strip()
            try:
                g.usuario = auth_obtener_usuario(token)
            except Exception:
                g.usuario = None
        if not g.usuario:
            return jsonify({
                "ok": False,
                "error": "Debes iniciar sesión para usar esta función",
                "requiere_login": True,
            }), 401
        return f(*args, **kwargs)
    return envoltura


# ---------------------------------------------------------------------------
# Datos geográficos — zona de cobertura actual del servicio.
# Por ahora FarmaPulse solo opera en estos 3 distritos de Lima; agregar
# más adelante es tan simple como sumar entradas a esta lista (no hay
# que tocar nada más, el frontend arma los selects a partir de esto).
# ---------------------------------------------------------------------------
UBICACIONES_PERU = {
    "Lima": {
        "Lima": ["San Borja", "San Luis", "La Victoria"],
    },
}

# ---------------------------------------------------------------------------
# Configuración del servicio de delivery (mostrada en el resumen de
# compra / checkout). Un solo lugar para editar zona, tiempo y costo.
# ---------------------------------------------------------------------------
ZONA_DELIVERY = ["San Borja", "San Luis", "La Victoria"]
TIEMPO_DELIVERY_MINUTOS = 35
COSTO_DELIVERY = 5.00

# ---------------------------------------------------------------------------
# Catálogo base para generación de datos simulados (fallback resiliente)
# ---------------------------------------------------------------------------
FARMACIAS_CADENA = ["Inkafarma", "Mifarma", "Boticas y Salud", "Farmacia Arcángel",
                     "Boticas Fasa", "Farmacias Felicidad"]
FARMACIAS_LOCALES = ["Botica San Martín", "Botica La Merced", "Botica Divino Niño",
                      "Botica Santa Rosa", "Botica El Ahorro"]

CATALOGO_MEDICAMENTOS = [
    {"nombre": "Ibuprofeno 400mg", "dci": "Ibuprofeno", "marca": "Doloral"},
    {"nombre": "Paracetamol 500mg", "dci": "Paracetamol", "marca": "Panadol"},
    {"nombre": "Amoxicilina 500mg", "dci": "Amoxicilina", "marca": "Amoxil"},
    {"nombre": "Loratadina 10mg", "dci": "Loratadina", "marca": "Clarityne"},
    {"nombre": "Omeprazol 20mg", "dci": "Omeprazol", "marca": "Losec"},
    {"nombre": "Metformina 850mg", "dci": "Metformina", "marca": "Glucophage"},
    {"nombre": "Losartán 50mg", "dci": "Losartán Potásico", "marca": "Cozaar"},
    {"nombre": "Azitromicina 500mg", "dci": "Azitromicina", "marca": "Zitromax"},
    {"nombre": "Diclofenaco 50mg", "dci": "Diclofenaco Sódico", "marca": "Cataflam"},
    {"nombre": "Cetirizina 10mg", "dci": "Cetirizina", "marca": "Zyrtec"},
]

PRESENTACIONES = ["Blíster x 10", "Caja x 10", "Caja x 20", "Blíster x 8", "Frasco x 1"]


# ---------------------------------------------------------------------------
# Utilidades de negocio
# ---------------------------------------------------------------------------
def _generar_datos_demo(termino_busqueda, departamento=None, provincia=None,
                         distrito=None, farmacia=None):
    """
    Genera resultados de DEMOSTRACIÓN en Soles (S/) para cuando ninguna
    farmacia registrada (ver scrapers/registry.py) devolvió resultados
    reales todavía — por ejemplo, mientras se termina de completar un
    scraper, o si todas las farmacias están momentáneamente caídas. Los
    precios y establecimientos son representativos del mercado peruano,
    no datos reales de inventario.
    """
    termino = (termino_busqueda or "").strip().lower()

    # Filtra el catálogo por coincidencia de nombre o principio activo (DCI).
    coincidencias = [
        med for med in CATALOGO_MEDICAMENTOS
        if termino in med["nombre"].lower() or termino in med["dci"].lower()
    ] if termino else CATALOGO_MEDICAMENTOS

    if not coincidencias:
        # Si no hay coincidencia exacta, se ofrece el catálogo completo
        # para que el usuario vea alternativas relacionadas.
        coincidencias = CATALOGO_MEDICAMENTOS[:4]

    resultados = []
    distrito_final = distrito or "San Borja"

    for med in coincidencias:
        # --- Versión GENÉRICA (usualmente más barata) ---
        precio_unit_generico = round(random.uniform(0.15, 0.60), 2)
        cantidad_generico = random.choice([8, 10, 20])
        farmacia_generica = farmacia or random.choice(FARMACIAS_LOCALES + FARMACIAS_CADENA)
        resultados.append({
            "id": str(uuid.uuid4()),
            "medicamento": med["nombre"],
            "dci": med["dci"],
            "tipo": "GENERICO",
            "farmacia": farmacia_generica,
            "distrito": distrito_final,
            "presentacion": f"Blíster x {cantidad_generico}",
            "precio_empaque": round(precio_unit_generico * cantidad_generico, 2),
            "precio_unitario": precio_unit_generico,
            "laboratorio": random.choice(
                ["Genfar", "Medifarma", "Portugal", "Farmindustria"]),
        })

        # --- Versión MARCA (usualmente más cara) ---
        precio_unit_marca = round(precio_unit_generico * random.uniform(2.5, 5.5), 2)
        cantidad_marca = random.choice([8, 10, 20])
        farmacia_marca = farmacia or random.choice(FARMACIAS_CADENA)
        resultados.append({
            "id": str(uuid.uuid4()),
            "medicamento": med["marca"],
            "dci": med["dci"],
            "tipo": "MARCA",
            "farmacia": farmacia_marca,
            "distrito": distrito_final,
            "presentacion": f"Caja x {cantidad_marca}",
            "precio_empaque": round(precio_unit_marca * cantidad_marca, 2),
            "precio_unitario": precio_unit_marca,
            "laboratorio": random.choice(
                ["Bayer", "Pfizer", "GSK", "Roche"]),
        })

    return resultados


def _calcular_ahorro_y_ordenar(resultados):
    """
    Ordena los resultados por precio unitario ascendente y calcula el
    porcentaje de ahorro del mejor genérico frente al precio de marca
    más alto disponible para el mismo principio activo (DCI).
    """
    if not resultados:
        return [], None

    resultados_ordenados = sorted(resultados, key=lambda r: r["precio_unitario"])

    mejor = resultados_ordenados[0]
    precios_marca = [r["precio_unitario"] for r in resultados if r["tipo"] == "MARCA"]

    ahorro_maximo = None
    if precios_marca:
        precio_marca_referencia = max(precios_marca)
        if precio_marca_referencia > 0:
            porcentaje = round(
                (1 - (mejor["precio_unitario"] / precio_marca_referencia)) * 100
            )
            ahorro_maximo = {
                "medicamento": mejor["medicamento"],
                "farmacia": mejor["farmacia"],
                "precio_unitario": mejor["precio_unitario"],
                "porcentaje_ahorro": max(porcentaje, 0),
                "precio_marca_referencia": precio_marca_referencia,
            }

    return resultados_ordenados, ahorro_maximo


# ---------------------------------------------------------------------------
# Rutas - Vistas HTML
# ---------------------------------------------------------------------------
@app.route("/")
def index():
    """Pantalla 1: Home / Hero Landing."""
    return render_template("index.html")


@app.route("/comparador")
def comparador():
    """Pantalla 2: Dashboard Comparador (precios en vivo de las farmacias registradas)."""
    return render_template("comparador.html", ubicaciones=UBICACIONES_PERU)


# ---------------------------------------------------------------------------
# Rutas - API
# ---------------------------------------------------------------------------
@app.route("/api/ubicaciones", methods=["GET"])
def api_ubicaciones():
    """Devuelve el árbol Departamento -> Provincia -> Distrito para los selects."""
    return jsonify({"ok": True, "data": UBICACIONES_PERU})


@app.route("/api/config", methods=["GET"])
def api_config():
    """Config pública para el frontend (número de WhatsApp, mensaje base,
    y datos del servicio de delivery mostrados en el checkout)."""
    return jsonify({
        "ok": True,
        "whatsapp_numero": WHATSAPP_NUMERO,
        "whatsapp_mensaje": "Hola FarmaPulse, quisiera coordinar un pedido/consulta de medicamentos 🙂",
        "zona_delivery": ZONA_DELIVERY,
        "tiempo_delivery_minutos": TIEMPO_DELIVERY_MINUTOS,
        "costo_delivery": COSTO_DELIVERY,
    })


# ---------------------------------------------------------------------------
# Rutas - Autenticación (Supabase Auth: correo + contraseña)
# ---------------------------------------------------------------------------
@app.route("/api/auth/registro", methods=["POST"])
@csrf.exempt
@limiter.limit("3 per hour")  # 🔒 Prevenir spam/fuerza bruta en registro
def api_auth_registro():
    if not _supabase_configurado():
        return jsonify({"ok": False, "error": "Supabase no está configurado en el servidor"}), 503

    body = request.get_json(silent=True) or {}
    email = (body.get("email") or "").strip().lower()
    password = body.get("password") or ""

    if not email or "@" not in email:
        return jsonify({"ok": False, "error": "Ingresa un correo válido"}), 400
    if len(password) < 6:
        return jsonify({"ok": False, "error": "La contraseña debe tener al menos 6 caracteres"}), 400

    try:
        datos = auth_registrar(email, password)
    except ValueError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400
    except requests.RequestException:
        return jsonify({"ok": False, "error": "No se pudo contactar el servicio de autenticación"}), 502

    requiere_confirmacion = not datos.get("access_token")
    return jsonify({
        "ok": True,
        "requiere_confirmacion": requiere_confirmacion,
        "usuario": datos.get("user"),
        "access_token": datos.get("access_token"),
        "refresh_token": datos.get("refresh_token"),
    })


@app.route("/api/auth/login", methods=["POST"])
@csrf.exempt
@limiter.limit("5 per 15 minutes")  # 🔒 Prevenir fuerza bruta en login
def api_auth_login():
    if not _supabase_configurado():
        return jsonify({"ok": False, "error": "Supabase no está configurado en el servidor"}), 503

    body = request.get_json(silent=True) or {}
    email = (body.get("email") or "").strip().lower()
    password = body.get("password") or ""

    if not email or not password:
        return jsonify({"ok": False, "error": "Ingresa correo y contraseña"}), 400

    try:
        datos = auth_iniciar_sesion(email, password)
    except ValueError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 401
    except requests.RequestException:
        return jsonify({"ok": False, "error": "No se pudo contactar el servicio de autenticación"}), 502

    return jsonify({
        "ok": True,
        "usuario": datos.get("user"),
        "access_token": datos.get("access_token"),
        "refresh_token": datos.get("refresh_token"),
    })


@app.route("/api/auth/logout", methods=["POST"])
@csrf.exempt
def api_auth_logout():
    auth_header = request.headers.get("Authorization", "")
    if auth_header.startswith("Bearer ") and _supabase_configurado():
        token = auth_header.removeprefix("Bearer ").strip()
        try:
            auth_cerrar_sesion(token)
        except requests.RequestException:
            pass
    return jsonify({"ok": True})


@app.route("/api/auth/sesion", methods=["GET"])
@sesion_opcional
def api_auth_sesion():
    if g.usuario:
        return jsonify({"ok": True, "autenticado": True, "usuario": g.usuario})
    return jsonify({"ok": True, "autenticado": False, "usuario": None})


@app.route("/api/buscar", methods=["GET", "POST"])
@csrf.exempt
@sesion_opcional  # buscar es libre; el login solo se recomienda en el frontend
def api_buscar():
    """
    Busca `producto` en todas las farmacias activas (ver
    scrapers/registry.py — hoy Inkafarma y Mifarma; agregar una más no
    requiere tocar esta ruta). Si ninguna farmacia devuelve resultados
    (por ejemplo, mientras se completan los selectores de un scraper),
    se usan datos de demostración para que el frontend nunca se quede
    sin nada que mostrar — queda marcado como "fuente": "demo".
    """
    if request.method == "POST":
        payload = request.get_json(silent=True) or {}
    else:
        payload = request.args

    termino = (payload.get("producto") or payload.get("termino") or "").strip()
    departamento = payload.get("departamento") or ""
    provincia = payload.get("provincia") or ""
    distrito = payload.get("distrito") or ""
    farmacia = payload.get("farmacia") or ""

    resultados = buscar_en_farmacias(termino, farmacia_filtro=farmacia or None)
    for r in resultados:
        r.setdefault("id", str(uuid.uuid4()))

    fuente = "farmacias" if resultados else "demo"
    if not resultados:
        resultados = _generar_datos_demo(
            termino, departamento, provincia, distrito, farmacia
        )

    resultados_ordenados, ahorro_maximo = _calcular_ahorro_y_ordenar(resultados)

    return jsonify({
        "ok": True,
        "fuente": fuente,
        "farmacias_consultadas": nombres_farmacias_activas(),
        "total": len(resultados_ordenados),
        "ahorro_maximo": ahorro_maximo,
        "resultados": resultados_ordenados,
        "consultado_en": datetime.now(timezone.utc).isoformat(),
    })


@app.route("/api/receta/guardar", methods=["POST"])
@csrf.exempt
@sesion_requerida
def api_receta_guardar():
    """
    Guarda un medicamento en "Mi Receta". Ahora requiere sesión iniciada
    (ver sesion_requerida) — ya no se acepta el id anónimo de invitado.
    Sin Supabase, va a memoria local.
    """
    body = request.get_json(silent=True) or {}

    requeridos = ["medicamento", "farmacia", "precio_unitario"]
    faltantes = [campo for campo in requeridos if campo not in body]
    if faltantes:
        return jsonify({
            "ok": False,
            "error": f"Faltan campos requeridos: {', '.join(faltantes)}"
        }), 400

    usuario_id = g.usuario["id"]

    registro = {
        "id": str(uuid.uuid4()),
        "usuario_id": usuario_id,
        "medicamento": body["medicamento"],
        "dci": body.get("dci", ""),
        "farmacia": body["farmacia"],
        "distrito": body.get("distrito", ""),
        "presentacion": body.get("presentacion", ""),
        "precio_unitario": body["precio_unitario"],
        "precio_empaque": body.get("precio_empaque"),
        "tipo": body.get("tipo", "GENERICO"),
        "creado_en": datetime.now(timezone.utc).isoformat(),
    }

    if supabase_client:
        try:
            resultado = (
                supabase_client.table("listas_recetas").insert(registro).execute()
            )
            return jsonify({"ok": True, "fuente": "supabase", "data": resultado.data})
        except Exception as exc:
            print(f"[FarmaPulse] Error al guardar en Supabase: {exc}")
            # Continúa hacia el fallback en memoria en vez de fallar la request.

    _MEMORIA_RECETAS.append(registro)
    return jsonify({"ok": True, "fuente": "memoria_local", "data": registro})


@app.route("/api/receta/historial", methods=["GET"])
@sesion_requerida
def api_receta_historial():
    """Historial de "Mi Receta": ahora requiere sesión iniciada."""
    usuario_id = g.usuario["id"]

    if supabase_client:
        try:
            resultado = (
                supabase_client.table("listas_recetas")
                .select("*")
                .eq("usuario_id", usuario_id)
                .order("creado_en", desc=True)
                .execute()
            )
            return jsonify({"ok": True, "fuente": "supabase", "data": resultado.data})
        except Exception as exc:
            print(f"[FarmaPulse] Error al leer historial de Supabase: {exc}")

    historial_local = [
        r for r in _MEMORIA_RECETAS if r["usuario_id"] == usuario_id
    ]
    return jsonify({"ok": True, "fuente": "memoria_local", "data": historial_local})


# ---------------------------------------------------------------------------
# Manejo de errores
# ---------------------------------------------------------------------------
@app.errorhandler(404)
def not_found(_error):
    return jsonify({"ok": False, "error": "Recurso no encontrado"}), 404


@app.errorhandler(500)
def server_error(_error):
    return jsonify({"ok": False, "error": "Error interno del servidor"}), 500

@app.after_request
def add_security_headers(response):
    """Agrega headers de seguridad HTTPS/HSTS"""
    response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-XSS-Protection"] = "1; mode=block"
    return response
    
# ---------------------------------------------------------------------------
# Punto de entrada
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    # debug=False en producción (previene exposición del debugger interactivo de Werkzeug)
    # Solo usar debug=True en desarrollo LOCAL
    debug_mode = os.getenv("FLASK_ENV") == "development"
    app.run(host="127.0.0.1", port=5000, debug=debug_mode)
