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
  - Checkout de pagos con Mercado Pago y comprobantes por correo.
  - Algoritmo de ordenamiento/ahorro por precio unitario.
  - Integración con Supabase para guardar/consultar "listas de receta".

Ejecutar:
    pip install -r requirements.txt
    playwright install chromium   # una sola vez
    python app.py
Luego abrir http://127.0.0.1:5000
"""

import os
import hashlib
import hmac
import random
import re
import smtplib
import ssl
import sqlite3
import time
import uuid
import unicodedata
from decimal import Decimal, InvalidOperation
from datetime import datetime, timezone
from email.message import EmailMessage
from functools import wraps
from pathlib import Path

import requests
from dotenv import load_dotenv
from flask import Flask, g, jsonify, render_template, request
from werkzeug.exceptions import HTTPException
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from flask_talisman import Talisman
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

from scrapers.registry import buscar_en_farmacias, nombres_farmacias_activas
from flask_wtf.csrf import CSRFProtect
from security import validar_contrasena
from identity_security import IdentitySecurity
from delivery_location import district_for_point
from payment_ledger import PaymentLedger
from mercado_pago import ORDER_ID, crear_orden, leer_orden

# ---------------------------------------------------------------------------
# Configuración inicial
# ---------------------------------------------------------------------------
# Cargar el archivo junto a la aplicación, aunque Flask se inicie desde otra
# carpeta (por ejemplo, desde un acceso directo o un proceso de desarrollo).
load_dotenv(Path(__file__).resolve().with_name(".env"))

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
identity_security = IdentitySecurity(
    os.getenv("IDENTITY_SECURITY_DB") or Path(app.instance_path) / "identity_security.sqlite3",
    os.getenv("IDENTITY_SECURITY_KEY") or SECRET_KEY,
)
payment_ledger = PaymentLedger(
    os.getenv("PAYMENTS_DB") or Path(app.instance_path) / "payments.sqlite3", SECRET_KEY,
)


@app.errorhandler(sqlite3.Error)
def manejar_error_seguridad_identidad(error):
    app.logger.error("El almacenamiento de seguridad de identidad no está disponible")
    return jsonify({"ok": False, "error": "No se pudo comprobar el acceso. Intenta nuevamente"}), 503


@app.errorhandler(HTTPException)
def manejar_error_http_api(error: HTTPException):
    if request.path.startswith("/api/"):
        return jsonify({"ok": False, "error": error.description}), error.code
    return error


@app.errorhandler(500)
def manejar_error_interno_api(error):
    if request.path.startswith("/api/"):
        app.logger.exception("Error interno en la ruta %s", request.path, exc_info=error)
        return jsonify({"ok": False, "error": "Ocurrió un error interno. Intenta nuevamente."}), 500
    return error

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
        "script-src": ["'self'", "cdn.jsdelivr.net", "cdnjs.cloudflare.com", "kit.fontawesome.com", "https://*.mercadopago.com", "https://*.mlstatic.com"],
        "connect-src": ["'self'", "https://*.mercadopago.com", "https://*.mercadopago.com.pe", "https://*.mlstatic.com"],
        "frame-src": ["'self'", "https://*.mercadopago.com", "https://*.mercadopago.com.pe", "https://*.mercadolibre.com", "https://*.mlstatic.com"],
        "style-src": ["'self'", "cdn.jsdelivr.net", "cdnjs.cloudflare.com", "fonts.googleapis.com"],
        "img-src": ["'self'", "data:", "https:"],
        "font-src": ["'self'", "fonts.gstatic.com", "cdnjs.cloudflare.com"],
    }
)

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
SUPABASE_ADMIN_KEY = (
    os.getenv("SUPABASE_SECRET_KEY") or os.getenv("SUPABASE_SERVICE_ROLE_KEY", "")
).strip()
RENIEC_TOKEN = os.getenv("RENIEC_TOKEN", "").strip()

MERCADO_PAGO_PUBLIC_KEY = os.getenv("MERCADO_PAGO_PUBLIC_KEY", "").strip()
MERCADO_PAGO_ACCESS_TOKEN = os.getenv("MERCADO_PAGO_ACCESS_TOKEN", "").strip()
MERCADO_PAGO_WEBHOOK_SECRET = os.getenv("MERCADO_PAGO_WEBHOOK_SECRET", "").strip()
MERCADO_PAGO_NOTIFICATION_URL = os.getenv("MERCADO_PAGO_NOTIFICATION_URL", "").strip()
MAIL_HOST = os.getenv("MAIL_HOST", "")
MAIL_PORT = int(os.getenv("MAIL_PORT", "587"))
MAIL_USERNAME = os.getenv("MAIL_USERNAME", "")
MAIL_PASSWORD = os.getenv("MAIL_PASSWORD", "")
MAIL_FROM = os.getenv("MAIL_FROM", MAIL_USERNAME)
_COTIZACIONES = URLSafeTimedSerializer(os.getenv("SECRET_KEY", ""), salt="farmapulse-cotizaciones")
_VALIDACION_DIRECCION = URLSafeTimedSerializer(
    os.getenv("SECRET_KEY", ""), salt="farmapulse-direccion-google"
)

def _pagos_configurados():
    return bool(MERCADO_PAGO_PUBLIC_KEY and MERCADO_PAGO_ACCESS_TOKEN
                and MAIL_HOST and MAIL_USERNAME and MAIL_PASSWORD and MAIL_FROM)


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


def auth_registrar(email: str, password: str, redirect_to: str) -> dict:
    respuesta = requests.post(
        _auth_url("/signup"), params={"redirect_to": redirect_to}, headers=_auth_headers(),
        json={"email": email, "password": password}, timeout=AUTH_TIMEOUT,
    )
    try:
        datos = respuesta.json()
    except requests.exceptions.JSONDecodeError as exc:
        raise requests.RequestException(
            "El servicio de autenticación devolvió una respuesta inválida"
        ) from exc
    if respuesta.status_code >= 400:
        raise ValueError(datos.get("msg") or datos.get("error_description") or "No se pudo registrar la cuenta")
    return datos


def auth_iniciar_sesion(email: str, password: str) -> dict:
    respuesta = requests.post(
        _auth_url("/token?grant_type=password"), headers=_auth_headers(),
        json={"email": email, "password": password}, timeout=AUTH_TIMEOUT,
    )
    try:
        datos = respuesta.json()
    except requests.exceptions.JSONDecodeError as exc:
        raise requests.RequestException(
            "El servicio de autenticación devolvió una respuesta inválida"
        ) from exc
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


def consultar_dni_reniec(dni: str) -> dict:
    """Consulta nombres por DNI sin exponer el token del proveedor al navegador."""
    respuesta = requests.get(
        "https://api.decolecta.com/v1/reniec/dni",
        params={"numero": dni},
        headers={"Authorization": f"Bearer {RENIEC_TOKEN}", "Accept": "application/json"},
        timeout=8,
    )
    if respuesta.status_code in (400, 404):
        raise LookupError("No encontramos datos para ese DNI")
    respuesta.raise_for_status()
    datos = respuesta.json()
    if not isinstance(datos, dict):
        raise ValueError("Respuesta de consulta DNI inválida")

    dni_devuelto = str(datos.get("document_number") or "")
    nombre = str(datos.get("full_name") or "").strip()
    if dni_devuelto != dni or not 2 <= len(nombre) <= 150:
        raise ValueError("Los datos recibidos no coinciden con el DNI consultado")
    return {"dni": dni_devuelto, "nombre": nombre, "fuente": "Decolecta"}


def _normalizar_nombre_persona(nombre: str) -> str:
    """Normaliza acentos, espacios y signos para comparar datos de identidad."""
    sin_acentos = unicodedata.normalize("NFKD", nombre)
    texto = "".join(caracter for caracter in sin_acentos if not unicodedata.combining(caracter))
    return " ".join(re.sub(r"[^A-Z0-9 ]", " ", texto.upper()).split())


def _identificadores_seguridad(usuario, cliente=None):
    identificadores = {
        "usuario": usuario.get("id"),
        "correo": (usuario.get("email") or "").strip().lower(),
    }
    if cliente:
        identificadores["dni"] = cliente["dni"]
        identificadores["identidad"] = f"{cliente['dni']}:{_normalizar_nombre_persona(cliente['nombre'])}"
    return identificadores


def _acceso_bloqueado(usuario, cliente=None):
    return identity_security.status(_identificadores_seguridad(usuario, cliente))["blocked"]


def _respuesta_acceso_bloqueado():
    return jsonify({
        "ok": False, "bloqueado": True, "intentos_restantes": 0,
        "error": "Acceso bloqueado permanentemente tras cinco fallos de validación de identidad.",
    }), 403


def _registrar_fallo_identidad(usuario, cliente):
    estado = identity_security.record_failure(_identificadores_seguridad(usuario, cliente))
    if estado["blocked"]:
        return _respuesta_acceso_bloqueado()
    restantes = estado["remaining"]
    return jsonify({
        "ok": False, "bloqueado": False, "intentos_restantes": restantes,
        "error": f"Los apellidos y nombres no coinciden con el DNI. Te quedan {restantes} intento(s) antes del bloqueo permanente.",
    }), 422


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
        if g.usuario and _acceso_bloqueado(g.usuario):
            return _respuesta_acceso_bloqueado()
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
        if request.endpoint != "api_auth_eliminar" and _acceso_bloqueado(g.usuario):
            return _respuesta_acceso_bloqueado()
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
    """Config pública para el frontend (pasarela de pago,
    y datos del servicio de delivery mostrados en el checkout)."""
    return jsonify({
        "ok": True,
        "mercado_pago_public_key": MERCADO_PAGO_PUBLIC_KEY,
        "pasarela_configurada": _pagos_configurados(),
        "zona_delivery": ZONA_DELIVERY,
        "tiempo_delivery_minutos": TIEMPO_DELIVERY_MINUTOS,
        "costo_delivery": COSTO_DELIVERY,
        "geocodificador_configurado": True,
    })


# ---------------------------------------------------------------------------
# Pagos con Mercado Pago y comprobantes por correo
# ---------------------------------------------------------------------------
def _enviar_comprobante(email: str, nombre: str, dni: str, cliente: dict, productos: list, subtotal: Decimal, delivery: Decimal, total: Decimal, pago_id: str) -> None:
    mensaje = EmailMessage()
    prueba = cliente.get("compra_prueba") is True
    mensaje["Subject"] = ("[PRUEBA] " if prueba else "") + f"Comprobante de compra FarmaPulse - {pago_id}"
    mensaje["From"] = MAIL_FROM
    mensaje["To"] = email
    lineas = [f"Hola {nombre}, tu compra fue realizada con éxito.", "", f"Comprobante de pago: {pago_id}", f"Nombre: {nombre}", f"DNI: {dni}", f"Correo: {email}", "", "Productos:"]
    if prueba:
        lineas[:0] = ["PRUEBA DE INTEGRACIÓN: no se realizó un cobro real ni un pedido para entregar.", ""]
    lineas.extend(f"- {p['medicamento']} ({p['presentacion']}) en {p['farmacia']}: S/ {p['precio']}" for p in productos)
    lineas.extend(["", f"Dirección de entrega: {cliente['direccion']}, {cliente['distrito']}",
                   f"Subtotal: S/ {subtotal:.2f}", f"Delivery: S/ {delivery:.2f}",
                   f"Total pagado: S/ {total:.2f}", "", "Este correo confirma el pago procesado por Mercado Pago."])
    mensaje.set_content("\n".join(lineas))
    with smtplib.SMTP(MAIL_HOST, MAIL_PORT, timeout=15) as servidor:
        servidor.starttls(context=ssl.create_default_context())
        servidor.login(MAIL_USERNAME, MAIL_PASSWORD)
        servidor.send_message(mensaje)


def _datos_checkout(items: list):
    if not isinstance(items, list) or not items or len(items) > 20:
        raise ValueError("El carrito no es válido")
    productos = []
    for item in items:
        if not isinstance(item, dict):
            raise ValueError("El carrito no es válido")
        cotizacion = _COTIZACIONES.loads(item.get("cotizacion", ""), max_age=1800)
        precio = Decimal(cotizacion["precio"])
        if not precio.is_finite() or precio <= 0:
            raise ValueError("El precio del carrito no es válido")
        productos.append(cotizacion)
    subtotal = sum((Decimal(p["precio"]) for p in productos), Decimal("0.00"))
    delivery = Decimal(str(COSTO_DELIVERY)).quantize(Decimal("0.01"))
    return productos, subtotal, delivery, subtotal + delivery


def _firmar_precio_producto(producto):
    precio = producto.get("precio_empaque")
    if precio is None:
        precio = producto.get("precio_unitario")
    precio = Decimal(str(precio)).quantize(Decimal("0.01"))
    if not precio.is_finite() or precio <= 0:
        raise ValueError("Precio no disponible")
    datos = {"medicamento": producto["medicamento"], "farmacia": producto["farmacia"],
             "presentacion": producto.get("presentacion") or "presentación única", "precio": str(precio)}
    return {**producto, "presentacion": datos["presentacion"], "precio_empaque": float(precio),
            "cotizacion": _COTIZACIONES.dumps(datos), "comprable": True}


def _identificador_producto(producto):
    return tuple(" ".join(unicodedata.normalize("NFC", str(producto.get(campo) or defecto)).casefold().split())
                 for campo, defecto in (("medicamento", ""), ("farmacia", ""), ("presentacion", "presentación única")))


@app.route("/api/checkout/cotizar", methods=["POST"])
@csrf.exempt
@limiter.limit("5 per minute")
@sesion_requerida
def api_checkout_cotizar():
    body = request.get_json(silent=True)
    items = body.get("productos") if isinstance(body, dict) else None
    if (not isinstance(items, list) or not 1 <= len(items) <= 20
            or any(not isinstance(item, dict) or any(
                not isinstance(item.get(campo), str) or not 1 <= len(item[campo].strip()) <= 250
                for campo in ("medicamento", "farmacia"))
                or (item.get("presentacion") is not None and (
                    not isinstance(item["presentacion"], str) or len(item["presentacion"]) > 250))
                for item in items)):
        return jsonify({"ok": False, "error": "El carrito no es válido"}), 400
    actualizados, consultas = [], {}
    for item in items:
        try:
            token = item.get("cotizacion", "")
            if not isinstance(token, str):
                raise ValueError
            datos = _COTIZACIONES.loads(token, max_age=1800)
            precio = Decimal(datos["precio"])
            if not precio.is_finite() or precio <= 0 or _identificador_producto(datos) != _identificador_producto(item):
                raise ValueError
            actualizados.append({**item, "precio_empaque": float(precio), "comprable": True})
            continue
        except (BadSignature, SignatureExpired, ValueError, KeyError, TypeError, InvalidOperation):
            pass
        clave = (item["medicamento"].strip(), item["farmacia"].strip())
        if clave not in consultas:
            consultas[clave] = buscar_en_farmacias(clave[0], farmacia_filtro=clave[1])
        coincidencias = [p for p in consultas[clave] if _identificador_producto(p) == _identificador_producto(item)]
        try:
            if not coincidencias or len({str(p.get("precio_empaque") if p.get("precio_empaque") is not None
                                               else p.get("precio_unitario")) for p in coincidencias}) != 1:
                raise ValueError
            actualizados.append(_firmar_precio_producto(coincidencias[0]))
        except (KeyError, TypeError, ValueError, InvalidOperation):
            return jsonify({"ok": False, "error": f"{item['medicamento']} ya no está disponible para compra en esa presentación. Retíralo del carrito o elige otra opción."}), 409
    subtotal = sum((Decimal(_COTIZACIONES.loads(p["cotizacion"])["precio"]) for p in actualizados), Decimal("0.00"))
    delivery = Decimal(str(COSTO_DELIVERY)).quantize(Decimal("0.01"))
    return jsonify({"ok": True, "productos": actualizados, "subtotal": str(subtotal),
                    "delivery": str(delivery), "total": str(subtotal + delivery)})


def _normalizar_texto(texto: str) -> str:
    sin_acentos = unicodedata.normalize("NFKD", texto)
    return "".join(caracter for caracter in sin_acentos if not unicodedata.combining(caracter)).casefold().strip()


def _consultar_sugerencias_direccion(texto: str, distrito: str = "") -> list:
    respuesta = requests.get(
        "https://photon.komoot.io/api/",
        params={"q": f"{texto}, {distrito}, Lima, Peru", "limit": 30,
                "lat": -12.085, "lon": -77.01, "zoom": 15,
                "bbox": "-77.06,-12.14,-76.96,-12.04"},
        headers={"User-Agent": "FarmaPulse/1.0", "Accept-Language": "es"}, timeout=8,
    )
    respuesta.raise_for_status()
    datos = respuesta.json()
    if not isinstance(datos, dict):
        raise ValueError("Respuesta inválida del servicio de mapas")
    palabras_omitidas = {"calle", "avenida", "av", "jiron", "jr", "pasaje", "psje", "de", "del", "la", "las", "los", "el"}
    palabras = set(re.findall(r"[a-z]+", _normalizar_texto(texto))) - palabras_omitidas
    numero_buscado = re.search(r"\b\d+[a-z]?\b", _normalizar_texto(texto))
    sugerencias, vistos = [], set()
    for feature in datos.get("features", []):
        if not isinstance(feature, dict):
            continue
        propiedades = feature.get("properties") or {}
        coordenadas = (feature.get("geometry") or {}).get("coordinates") or []
        if not isinstance(propiedades, dict) or len(coordenadas) != 2:
            continue
        longitud, latitud = coordenadas
        distrito_real = district_for_point(latitud, longitud)
        if not distrito_real or (distrito and distrito_real != distrito):
            continue
        tipo = propiedades.get("type")
        if tipo in {"country", "state", "county", "city", "district", "locality"}:
            continue
        calle = str(propiedades.get("street") or "").strip()
        numero = str(propiedades.get("housenumber") or "").strip()
        nombre = str(propiedades.get("name") or calle).strip()
        if not calle and tipo not in {"street", "house"}:
            continue
        palabras_calle = set(re.findall(r"[a-z]+", _normalizar_texto(calle or nombre)))
        if palabras and len(palabras & palabras_calle) / len(palabras) < 0.6:
            continue
        if numero_buscado and numero and _normalizar_texto(numero) != numero_buscado.group():
            continue
        principal = f"{calle} {numero}".strip() if calle else nombre
        if not principal:
            continue
        descripcion = f"{principal}, {distrito_real}"
        clave = (descripcion, round(latitud, 5), round(longitud, 5))
        if clave in vistos:
            continue
        vistos.add(clave)
        sugerencias.append({
            "descripcion": descripcion, "latitud": latitud, "longitud": longitud,
            "distrito": distrito_real, "direccion_precisa": bool(calle and numero),
        })
    return sorted(sugerencias, key=lambda lugar: not lugar["direccion_precisa"])[:6]


@app.route("/api/direcciones/sugerencias", methods=["POST"])
@csrf.exempt
@limiter.limit("20 per minute")
@sesion_requerida
def api_sugerencias_direccion():
    body = request.get_json(silent=True) or {}
    texto = body.get("texto", "") if isinstance(body, dict) else ""
    if not isinstance(texto, str) or not 3 <= len(texto.strip()) <= 120:
        return jsonify({"ok": False, "error": "Escribe al menos 3 caracteres de la dirección"}), 400
    try:
        distrito = body.get("distrito") or ""
        if distrito and distrito not in ZONA_DELIVERY:
            return jsonify({"ok": False, "error": "Selecciona un distrito de reparto"}), 400
        sugerencias = _consultar_sugerencias_direccion(texto.strip(), distrito)
    except (requests.RequestException, ValueError):
        app.logger.warning("No se pudieron consultar sugerencias del geocodificador")
        return jsonify({"ok": False, "error": "No se pudo consultar el mapa abierto. Intenta nuevamente"}), 502
    return jsonify({"ok": True, "sugerencias": sugerencias})


@app.route("/api/direcciones/validar", methods=["POST"])
@csrf.exempt
@limiter.limit("10 per minute")
@sesion_requerida
def api_validar_direccion():
    body = request.get_json(silent=True) or {}
    if not isinstance(body, dict):
        return jsonify({"ok": False, "error": "La solicitud no es válida"}), 400
    latitud, longitud = body.get("latitud"), body.get("longitud")
    direccion = body.get("direccion")
    distrito = district_for_point(latitud, longitud)
    if not distrito:
        return jsonify({"ok": False, "error": "Ese punto está fuera de nuestra zona de reparto"}), 400
    if not isinstance(direccion, str) or not 5 <= len(direccion.strip()) <= 250:
        return jsonify({"ok": False, "error": "Ingresa la calle, número o referencia de entrega"}), 400
    lugar = {
        "place_id": f"punto:{latitud:.6f},{longitud:.6f}", "direccion": direccion.strip(),
        "distrito": distrito, "latitud": latitud, "longitud": longitud,
    }
    return jsonify({"ok": True, **lugar, "validacion": _VALIDACION_DIRECCION.dumps(lugar)})


def _datos_cliente_checkout(body: dict) -> dict:
    apellidos = body.get("apellidos")
    nombres = body.get("nombres")
    dni = body.get("dni")
    telefono = body.get("telefono")
    distrito = body.get("distrito")
    direccion = body.get("direccion")
    place_id = body.get("place_id")
    token_direccion = body.get("direccion_validacion")
    if (not isinstance(apellidos, str) or not 2 <= len(apellidos.strip()) <= 80
            or not isinstance(nombres, str) or not 2 <= len(nombres.strip()) <= 80
            or not isinstance(dni, str) or not re.fullmatch(r"\d{8}", dni)
            or not isinstance(telefono, str) or not re.fullmatch(r"9\d{8}", telefono)
            or distrito not in ZONA_DELIVERY
            or not isinstance(direccion, str) or not 5 <= len(direccion.strip()) <= 250
            or not isinstance(place_id, str) or not isinstance(token_direccion, str)):
        raise ValueError("Completa los datos y selecciona una dirección del mapa")
    apellidos_limpios, nombres_limpios = apellidos.strip(), nombres.strip()
    try:
        direccion_verificada = _VALIDACION_DIRECCION.loads(token_direccion, max_age=1800)
    except (BadSignature, SignatureExpired, TypeError):
        raise ValueError("La selección de la dirección venció. Búscala nuevamente en el mapa") from None
    if (not isinstance(direccion_verificada, dict)
            or district_for_point(direccion_verificada.get("latitud"), direccion_verificada.get("longitud")) != distrito
            or direccion_verificada.get("place_id") != place_id
            or direccion_verificada.get("direccion") != direccion.strip()
            or direccion_verificada.get("distrito") != distrito
            or distrito not in ZONA_DELIVERY):
        raise ValueError("La dirección o el distrito no coinciden con la selección del mapa")
    return {
        "apellidos": apellidos_limpios, "nombres": nombres_limpios,
        "nombre": f"{apellidos_limpios} {nombres_limpios}", "dni": dni,
        "telefono": telefono,
        "distrito": distrito, "direccion": direccion.strip(), "place_id": place_id,
        "latitud": direccion_verificada["latitud"], "longitud": direccion_verificada["longitud"],
    }


@app.route("/api/checkout/orden", methods=["POST"])
@csrf.exempt
@limiter.limit("5 per minute")
@sesion_requerida
def api_checkout_orden():
    if not _pagos_configurados():
        return jsonify({"ok": False, "error": "La pasarela o el correo no están configurados"}), 503
    body = request.get_json(silent=True) or {}
    if not isinstance(body, dict):
        return jsonify({"ok": False, "error": "La solicitud no es válida"}), 400
    try:
        cliente = _datos_cliente_checkout(body)
    except ValueError as error:
        return jsonify({"ok": False, "error": str(error)}), 400
    nombre, dni = cliente["nombre"], cliente["dni"]
    if _acceso_bloqueado(g.usuario, cliente):
        return _respuesta_acceso_bloqueado()
    email = (g.usuario.get("email") or "").strip().lower()
    if len(nombre) < 2 or len(nombre) > 161 or not dni.isdigit() or len(dni) != 8 or not email:
        return jsonify({"ok": False, "error": "Ingresa tus apellidos, nombres y un DNI válido de 8 dígitos"}), 400
    try:
        _, _, _, total = _datos_checkout(body.get("productos") or [])
    except (BadSignature, SignatureExpired, KeyError, InvalidOperation, TypeError, ValueError):
        return jsonify({"ok": False, "error": "El carrito cambió o la cotización venció. Actualiza e intenta de nuevo"}), 400

    centimos = int(total * 100)
    if centimos < 1 or centimos > 700000:
        return jsonify({"ok": False, "error": "El total está fuera del rango permitido por Mercado Pago"}), 400
    if not RENIEC_TOKEN:
        return jsonify({"ok": False, "error": "La validación del DNI no está disponible en este momento"}), 503
    try:
        persona = consultar_dni_reniec(dni)
    except LookupError:
        return _registrar_fallo_identidad(g.usuario, cliente)
    except requests.Timeout:
        return jsonify({"ok": False, "error": "La consulta de DNI tardó demasiado. Intenta nuevamente"}), 504
    except (requests.RequestException, ValueError):
        app.logger.warning("No se pudo completar la consulta de DNI con el proveedor")
        return jsonify({"ok": False, "error": "No se pudo validar la identidad. Intenta nuevamente"}), 502
    if _normalizar_nombre_persona(nombre) != _normalizar_nombre_persona(persona["nombre"]):
        return _registrar_fallo_identidad(g.usuario, cliente)
    if _acceso_bloqueado(g.usuario, cliente):
        return _respuesta_acceso_bloqueado()
    orden_id = f"fp_{uuid.uuid4().hex}"
    firma = _COTIZACIONES.dumps({**cliente, "id": orden_id, "amount": centimos, "email": email,
                               "identidad_validada": True, "usuario_id": g.usuario.get("id")})
    return jsonify({"ok": True, "orden_id": orden_id, "orden_firma": firma, "amount": centimos,
                    "pagador": {"nombre": f"{cliente['nombres']} {cliente['apellidos']}", "dni": dni}})


@app.route("/api/checkout/pagar", methods=["POST"])
@csrf.exempt
@limiter.limit("5 per minute")
@sesion_requerida
def api_checkout_pagar():
    if not _pagos_configurados():
        return jsonify({"ok": False, "error": "La pasarela o el correo no están configurados"}), 503
    body = request.get_json(silent=True) or {}
    if not isinstance(body, dict):
        return jsonify({"ok": False, "error": "La solicitud no es válida"}), 400
    try:
        cliente = _datos_cliente_checkout(body)
    except ValueError as error:
        return jsonify({"ok": False, "error": str(error)}), 400
    nombre, dni = cliente["nombre"], cliente["dni"]
    if _acceso_bloqueado(g.usuario, cliente):
        return _respuesta_acceso_bloqueado()
    token = body.get("token")
    method = body.get("payment_method_id")
    payment_type = body.get("payment_type_id")
    issuer = body.get("issuer_id")
    installments = body.get("installments")
    if (not isinstance(token, str) or not re.fullmatch(r"[a-fA-F0-9]{32}", token)
            or not isinstance(method, str) or not re.fullmatch(r"[a-zA-Z0-9_]{1,40}", method)
            or payment_type not in {"credit_card", "debit_card"}
            or isinstance(installments, bool) or not re.fullmatch(r"\d{1,2}", str(installments))
            or not 1 <= int(installments) <= 48
            or (issuer not in (None, "") and not re.fullmatch(r"\d{1,20}", str(issuer)))):
        return jsonify({"ok": False, "error": "Los datos del pago con tarjeta no son válidos"}), 400
    orden_firma = body.get("orden_firma")
    if not isinstance(orden_firma, str):
        return jsonify({"ok": False, "error": "La orden no es válida"}), 400
    email = (g.usuario.get("email") or "").strip().lower()
    try:
        productos, subtotal, delivery, total = _datos_checkout(body.get("productos") or [])
        orden = _COTIZACIONES.loads(orden_firma, max_age=1800)
        if (not isinstance(orden, dict) or orden.get("identidad_validada") is not True
                or orden.get("email") != email or orden.get("amount") != int(total * 100)
                or any(orden.get(campo) != valor for campo, valor in cliente.items())
                or orden.get("usuario_id") != g.usuario.get("id")
                or not orden.get("id", "").startswith("fp_")):
            raise ValueError
    except (BadSignature, SignatureExpired, KeyError, InvalidOperation, TypeError, ValueError):
        return jsonify({"ok": False, "error": "La orden o la cotización no corresponden a esta compra"}), 400

    previous = payment_ledger.claim(orden["id"], token, "", str(g.usuario["id"]))
    if previous:
        result, status = previous
        return jsonify(result), status
    payment_ledger.set_context(orden["id"], {
        "email": email, "cliente": cliente, "productos": productos,
        "subtotal": str(subtotal), "delivery": str(delivery), "total": str(total),
    })
    payload = crear_orden(orden["id"], total, email, cliente, token, method, payment_type, int(installments))
    try:
        respuesta = requests.post("https://api.mercadopago.com/v1/orders",
            headers={"Authorization": f"Bearer {MERCADO_PAGO_ACCESS_TOKEN}", "Content-Type": "application/json",
                     "X-Idempotency-Key": orden["id"]}, json=payload, timeout=20)
        datos = respuesta.json()
    except (requests.RequestException, ValueError):
        return _pago_sin_confirmar(orden["id"])
    if respuesta.status_code >= 500 or respuesta.status_code == 429 or not isinstance(datos, dict):
        return _pago_sin_confirmar(orden["id"])
    if respuesta.status_code >= 400:
        result = {"ok": False, "estado": "rechazado", "pago_confirmado": False,
                  "error": "Mercado Pago no pudo procesar la tarjeta. Revisa los datos o utiliza otra tarjeta"}
        if respuesta.status_code in (401, 403):
            result["error"] = "La configuración de Mercado Pago necesita revisión. Contacta a soporte"
        payment_ledger.finish(orden["id"], "rejected", result, 402)
        return jsonify(result), 402
    return _procesar_resultado_mercado_pago(orden["id"], datos)


def _pago_sin_confirmar(orden_id):
    result = {"ok": False, "estado": "sin_confirmar", "referencia": orden_id,
              "error": "No se pudo confirmar el resultado. No repitas el pago; contacta a soporte con la referencia " + orden_id}
    payment_ledger.finish(orden_id, "unknown", result, 502)
    return jsonify(result), 502


def _procesar_resultado_mercado_pago(orden_id, datos):
    record = payment_ledger.get(orden_id)
    if not record or not record["context"]:
        return jsonify({"ok": False, "error": "La orden no existe"}), 404
    context = record["context"]
    try:
        resultado = leer_orden(datos, orden_id, Decimal(context["total"]))
    except (ValueError, InvalidOperation, KeyError, TypeError, AttributeError):
        return _pago_sin_confirmar(orden_id)
    pago_id, status = resultado["pago_id"], resultado["status"]
    base = {"ok": False, "pago_id": pago_id, "orden_proveedor": resultado["orden_proveedor"],
            "status": status, "status_detail": resultado["status_detail"],
            "pago_confirmado": False, "referencia": orden_id}
    if resultado["estado"] == "approved":
        result = {**base, "ok": True, "estado": "aprobado", "pago_confirmado": True,
                  "comprobante_enviado": False, "mensaje": "Pago aprobado; el comprobante está pendiente de envío"}
        payment_ledger.settle(orden_id, "approved", result, 200)
        return jsonify(_entregar_comprobante(orden_id)), 200
    if resultado["estado"] == "pending":
        result = {**base, "estado": "pendiente", "error": "Tu pago está pendiente de confirmación. No vuelvas a pagar"}
        if resultado.get("challenge_url"):
            result["challenge_url"] = resultado["challenge_url"]
        saved, status_code, _ = payment_ledger.settle(orden_id, "pending", result, 202)
        return jsonify(saved), status_code
    if resultado["estado"] == "rejected":
        result = {**base, "estado": "rechazado", "error": "El pago no fue aprobado. Revisa la tarjeta o utiliza otra"}
        saved, status_code, _ = payment_ledger.settle(orden_id, "rejected", result, 402)
        return jsonify(saved), status_code
    return _pago_sin_confirmar(orden_id)


def _entregar_comprobante(orden_id):
    record = payment_ledger.get(orden_id)
    if payment_ledger.claim_receipt(orden_id):
        context, result = record["context"], record["response"]
        cliente = {**context["cliente"], "compra_prueba": result["orden_proveedor"].startswith("ORDTST")}
        try:
            _enviar_comprobante(context["email"], cliente["nombre"], cliente["dni"], cliente,
                context["productos"], Decimal(context["subtotal"]), Decimal(context["delivery"]),
                Decimal(context["total"]), result["pago_id"])
        except (smtplib.SMTPException, OSError):
            app.logger.warning("No se pudo enviar el comprobante del pago %s", result["pago_id"])
        else:
            result.update(comprobante_enviado=True, mensaje="Tu compra fue realizada con éxito")
            payment_ledger.finish(orden_id, "approved", result, 200)
        finally:
            payment_ledger.release_receipt(orden_id)
    return payment_ledger.get(orden_id)["response"]


@app.cli.command("reenviar-comprobantes")
def reenviar_comprobantes():
    """Reintenta correos pendientes sin generar cargos nuevos."""
    for orden_id in payment_ledger.pending_receipts():
        _entregar_comprobante(orden_id)


@app.route("/api/checkout/estado/<orden_id>", methods=["GET"])
@limiter.limit("30 per minute")
@sesion_requerida
def api_checkout_estado(orden_id):
    record = payment_ledger.get(orden_id, str(g.usuario["id"]))
    if not record:
        return jsonify({"ok": False, "error": "La orden no existe"}), 404
    result = record["response"]
    if record["state"] == "approved":
        return jsonify(_entregar_comprobante(orden_id)), 200
    if record["state"] != "pending" or not result or not result.get("orden_proveedor"):
        return jsonify(result or {"ok": False, "estado": "procesando"}), record["status"] or 202
    try:
        response = requests.get(f"https://api.mercadopago.com/v1/orders/{result['orden_proveedor']}",
            headers={"Authorization": f"Bearer {MERCADO_PAGO_ACCESS_TOKEN}"}, timeout=10)
        response.raise_for_status()
        data = response.json()
    except (requests.RequestException, ValueError):
        return jsonify(result), 202
    if not isinstance(data, dict) or str(data.get("id")) != result["orden_proveedor"]:
        return jsonify(result), 202
    return _procesar_resultado_mercado_pago(orden_id, data)


@app.route("/api/pagos/mercadopago/webhook", methods=["POST"])
@csrf.exempt
@limiter.limit("60 per minute")
def api_mercado_pago_webhook():
    if not MERCADO_PAGO_WEBHOOK_SECRET or not MERCADO_PAGO_ACCESS_TOKEN:
        return jsonify({"ok": False}), 503
    payment_id = request.args.get("data.id", "")
    request_id = request.headers.get("x-request-id", "")
    signature = dict(part.strip().split("=", 1) for part in request.headers.get("x-signature", "").split(",") if "=" in part)
    timestamp, supplied = signature.get("ts", ""), signature.get("v1", "")
    if not ORDER_ID.fullmatch(payment_id) or not request_id or not timestamp.isdigit() or not supplied:
        return jsonify({"ok": False}), 401
    manifest = f"id:{payment_id};request-id:{request_id};ts:{timestamp};"
    expected = hmac.new(MERCADO_PAGO_WEBHOOK_SECRET.encode(), manifest.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, supplied):
        return jsonify({"ok": False}), 401
    try:
        response = requests.get(f"https://api.mercadopago.com/v1/orders/{payment_id}",
            headers={"Authorization": f"Bearer {MERCADO_PAGO_ACCESS_TOKEN}"}, timeout=10)
        response.raise_for_status()
        data = response.json()
    except (requests.RequestException, ValueError):
        return jsonify({"ok": False}), 502
    if not isinstance(data, dict) or str(data.get("id")) != payment_id:
        return jsonify({"ok": False}), 502
    reference = data.get("external_reference")
    if not isinstance(reference, str) or not payment_ledger.get(reference):
        return jsonify({"ok": True})
    result, status_code = _procesar_resultado_mercado_pago(reference, data)
    return jsonify({"ok": status_code < 500}), 200 if status_code < 500 else 502


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
    if _acceso_bloqueado({"email": email}):
        return _respuesta_acceso_bloqueado()
    contrasena_valida, mensaje_contrasena = validar_contrasena(password)
    if not contrasena_valida:
        return jsonify({"ok": False, "error": mensaje_contrasena}), 400

    try:
        # Devolver al mismo FarmaPulse donde se inició el registro. En desarrollo
        # usa el host local actual; en producción APP_BASE_URL fija el dominio.
        base_url = os.getenv("APP_BASE_URL", "").strip().rstrip("/") or request.host_url.rstrip("/")
        datos = auth_registrar(email, password, f"{base_url}/comparador")
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
    if _acceso_bloqueado({"email": email}):
        return _respuesta_acceso_bloqueado()

    try:
        datos = auth_iniciar_sesion(email, password)
    except ValueError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 401
    except requests.RequestException:
        return jsonify({"ok": False, "error": "No se pudo contactar el servicio de autenticación"}), 502

    if _acceso_bloqueado(datos.get("user") or {"email": email}):
        return _respuesta_acceso_bloqueado()
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


@app.route("/api/auth/eliminar", methods=["POST"])
@csrf.exempt
@limiter.limit("3 per hour")
@sesion_requerida
def api_auth_eliminar():
    if not SUPABASE_ADMIN_KEY:
        return jsonify({
            "ok": False,
            "error": "La eliminación de cuentas no está configurada en el servidor",
        }), 503

    body = request.get_json(silent=True) or {}
    password = body.get("password") if isinstance(body, dict) else None
    email = (g.usuario.get("email") or "").strip().lower()
    if not isinstance(password, str) or not password or not email:
        return jsonify({"ok": False, "error": "Confirma tu contraseña para continuar"}), 400

    try:
        sesion_confirmada = auth_iniciar_sesion(email, password)
    except ValueError:
        return jsonify({"ok": False, "error": "La contraseña no es correcta"}), 401
    except requests.RequestException:
        return jsonify({"ok": False, "error": "No se pudo verificar tu contraseña"}), 502

    usuario_confirmado = sesion_confirmada.get("user") or {}
    usuario_id = g.usuario.get("id")
    if not usuario_id or usuario_confirmado.get("id") != usuario_id:
        return jsonify({"ok": False, "error": "No se pudo verificar la cuenta actual"}), 401

    try:
        respuesta = requests.delete(
            f"{SUPABASE_URL.rstrip('/')}/auth/v1/admin/users/{usuario_id}",
            headers={
                "apikey": SUPABASE_ADMIN_KEY,
                "Authorization": f"Bearer {SUPABASE_ADMIN_KEY}",
                "Content-Type": "application/json",
            },
            timeout=AUTH_TIMEOUT,
        )
    except requests.RequestException:
        return jsonify({"ok": False, "error": "No se pudo completar la eliminación de la cuenta"}), 502

    if respuesta.status_code not in (200, 204):
        app.logger.warning("Supabase rechazó la eliminación de una cuenta (HTTP %s)", respuesta.status_code)
        return jsonify({"ok": False, "error": "No se pudo eliminar la cuenta. Inténtalo nuevamente"}), 502

    _MEMORIA_RECETAS[:] = [r for r in _MEMORIA_RECETAS if r.get("usuario_id") != usuario_id]
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
    for indice, producto in enumerate(resultados_ordenados):
        producto["comprable"] = False
        if fuente == "farmacias":
            try:
                resultados_ordenados[indice] = _firmar_precio_producto(producto)
            except (KeyError, TypeError, ValueError, InvalidOperation):
                producto.pop("cotizacion", None)

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
    from local_https import run_local_server
    run_local_server(app)
