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
  - Checkout de pagos con Culqi y comprobantes por correo.
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
import re
import smtplib
import time
import uuid
from decimal import Decimal, InvalidOperation
from datetime import datetime, timezone
from email.message import EmailMessage
from functools import wraps

import requests
from dotenv import load_dotenv
from flask import Flask, g, jsonify, render_template, request
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from flask_talisman import Talisman
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

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
        "script-src": ["'self'", "cdn.jsdelivr.net", "cdnjs.cloudflare.com", "kit.fontawesome.com", "js.culqi.com"],
        "connect-src": ["'self'", "https://api.culqi.com"],
        "frame-src": ["'self'", "https://checkout.culqi.com"],
        "style-src": ["'self'", "cdn.jsdelivr.net", "cdnjs.cloudflare.com", "fonts.googleapis.com"],
        "img-src": ["'self'", "data:", "https:"],
        "font-src": ["'self'", "fonts.gstatic.com", "cdnjs.cloudflare.com"],
    }
)

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")

CULQI_PUBLIC_KEY = os.getenv("CULQI_PUBLIC_KEY", "")
CULQI_SECRET_KEY = os.getenv("CULQI_SECRET_KEY", "")
MAIL_HOST = os.getenv("MAIL_HOST", "")
MAIL_PORT = int(os.getenv("MAIL_PORT", "587"))
MAIL_USERNAME = os.getenv("MAIL_USERNAME", "")
MAIL_PASSWORD = os.getenv("MAIL_PASSWORD", "")
MAIL_FROM = os.getenv("MAIL_FROM", MAIL_USERNAME)
_COTIZACIONES = URLSafeTimedSerializer(os.getenv("SECRET_KEY", ""), salt="farmapulse-cotizaciones")

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
    """Config pública para el frontend (pasarela de pago,
    y datos del servicio de delivery mostrados en el checkout)."""
    return jsonify({
        "ok": True,
        "culqi_public_key": CULQI_PUBLIC_KEY,
        "pasarela_configurada": bool(CULQI_PUBLIC_KEY and CULQI_SECRET_KEY and MAIL_HOST and MAIL_USERNAME and MAIL_PASSWORD and MAIL_FROM),
        "zona_delivery": ZONA_DELIVERY,
        "tiempo_delivery_minutos": TIEMPO_DELIVERY_MINUTOS,
        "costo_delivery": COSTO_DELIVERY,
    })


# ---------------------------------------------------------------------------
# Pagos con Culqi y comprobantes por correo
# ---------------------------------------------------------------------------
def _enviar_comprobante(email: str, nombre: str, dni: str, cliente: dict, productos: list, subtotal: Decimal, delivery: Decimal, total: Decimal, cargo_id: str) -> None:
    mensaje = EmailMessage()
    mensaje["Subject"] = f"Comprobante de compra FarmaPulse - {cargo_id}"
    mensaje["From"] = MAIL_FROM
    mensaje["To"] = email
    lineas = [f"Hola {nombre}, tu compra fue realizada con éxito.", "", f"Comprobante de pago: {cargo_id}", f"Nombre: {nombre}", f"DNI: {dni}", f"Correo: {email}", "", "Productos:"]
    lineas.extend(f"- {p['medicamento']} ({p['presentacion']}) en {p['farmacia']}: S/ {p['precio']}" for p in productos)
    lineas.extend(["", f"Dirección de entrega: {cliente['direccion']}, {cliente['distrito']}",
                   f"Subtotal: S/ {subtotal:.2f}", f"Delivery: S/ {delivery:.2f}",
                   f"Total pagado: S/ {total:.2f}", "", "Este correo confirma el pago procesado por Culqi."])
    mensaje.set_content("\n".join(lineas))
    with smtplib.SMTP(MAIL_HOST, MAIL_PORT, timeout=15) as servidor:
        servidor.starttls()
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


def _datos_cliente_checkout(body: dict) -> dict:
    nombre = body.get("nombre")
    dni = body.get("dni")
    telefono = body.get("telefono")
    distrito = body.get("distrito")
    direccion = body.get("direccion")
    if (not isinstance(nombre, str) or not 2 <= len(nombre.strip()) <= 120
            or not isinstance(dni, str) or not re.fullmatch(r"\d{8}", dni)
            or not isinstance(telefono, str) or not re.fullmatch(r"9\d{8}", telefono)
            or distrito not in ZONA_DELIVERY
            or not isinstance(direccion, str) or not 5 <= len(direccion.strip()) <= 250):
        raise ValueError("Completa los datos de entrega, nombre y DNI para continuar")
    return {
        "nombre": nombre.strip(), "dni": dni, "telefono": telefono,
        "distrito": distrito, "direccion": direccion.strip(),
    }


@app.route("/api/checkout/orden", methods=["POST"])
@csrf.exempt
@limiter.limit("5 per minute")
@sesion_requerida
def api_checkout_orden():
    if not (CULQI_PUBLIC_KEY and CULQI_SECRET_KEY and MAIL_HOST and MAIL_USERNAME and MAIL_PASSWORD and MAIL_FROM):
        return jsonify({"ok": False, "error": "La pasarela o el correo no están configurados"}), 503
    body = request.get_json(silent=True) or {}
    if not isinstance(body, dict):
        return jsonify({"ok": False, "error": "La solicitud no es válida"}), 400
    try:
        cliente = _datos_cliente_checkout(body)
    except ValueError as error:
        return jsonify({"ok": False, "error": str(error)}), 400
    nombre, dni = cliente["nombre"], cliente["dni"]
    email = (g.usuario.get("email") or "").strip().lower()
    if len(nombre) < 2 or len(nombre) > 120 or not dni.isdigit() or len(dni) != 8 or not email:
        return jsonify({"ok": False, "error": "Ingresa tu nombre y un DNI válido de 8 dígitos"}), 400
    try:
        _, _, _, total = _datos_checkout(body.get("productos") or [])
    except (BadSignature, SignatureExpired, KeyError, InvalidOperation, TypeError, ValueError):
        return jsonify({"ok": False, "error": "El carrito cambió o la cotización venció. Actualiza e intenta de nuevo"}), 400

    centimos = int(total * 100)
    if centimos < 600 or centimos > 700000:
        return jsonify({"ok": False, "error": "El total está fuera del rango permitido por Culqi"}), 400
    nombres = nombre.split(maxsplit=1)
    try:
        respuesta = requests.post("https://api.culqi.com/v2/orders",
            headers={"Authorization": f"Bearer {CULQI_SECRET_KEY}", "Content-Type": "application/json"},
            json={"amount": centimos, "currency_code": "PEN", "description": "Compra FarmaPulse",
                  "order_number": f"fp-{uuid.uuid4().hex}", "expiration_date": str(int(time.time()) + 1800),
                  "client_details": {"first_name": nombres[0], "last_name": nombres[-1], "email": email,
                                     "phone_number": f"+51{cliente['telefono']}"},
                  "metadata": {"dni": dni, "distrito": cliente["distrito"], "direccion": cliente["direccion"]}}, timeout=20)
        datos = respuesta.json()
    except (requests.RequestException, ValueError):
        return jsonify({"ok": False, "error": "No se pudo preparar el pago con Culqi"}), 502
    if respuesta.status_code >= 400 or not isinstance(datos, dict) or not datos.get("id", "").startswith(("ord_test_", "ord_live_")):
        mensaje = (datos.get("user_message") or datos.get("merchant_message")) if isinstance(datos, dict) else None
        return jsonify({"ok": False, "error": mensaje or "Culqi no pudo preparar el pago"}), 502
    firma = _COTIZACIONES.dumps({**cliente, "id": datos["id"], "amount": centimos, "email": email})
    return jsonify({"ok": True, "orden_id": datos["id"], "orden_firma": firma, "amount": centimos})


@app.route("/api/checkout/pagar", methods=["POST"])
@csrf.exempt
@limiter.limit("5 per minute")
@sesion_requerida
def api_checkout_pagar():
    if not (CULQI_PUBLIC_KEY and CULQI_SECRET_KEY and MAIL_HOST and MAIL_USERNAME and MAIL_PASSWORD and MAIL_FROM):
        return jsonify({"ok": False, "error": "La pasarela o el correo no están configurados"}), 503
    body = request.get_json(silent=True) or {}
    if not isinstance(body, dict):
        return jsonify({"ok": False, "error": "La solicitud no es válida"}), 400
    try:
        cliente = _datos_cliente_checkout(body)
    except ValueError as error:
        return jsonify({"ok": False, "error": str(error)}), 400
    nombre, dni = cliente["nombre"], cliente["dni"]
    token, items = (body.get("token") or "").strip(), body.get("productos") or []
    orden_firma = (body.get("orden_firma") or "").strip()
    email = (g.usuario.get("email") or "").strip().lower()
    if len(nombre) < 2 or len(nombre) > 120 or not dni.isdigit() or len(dni) != 8:
        return jsonify({"ok": False, "error": "Ingresa tu nombre y un DNI válido de 8 dígitos"}), 400
    if (not email or not token.startswith(("tkn_test_", "tkn_live_", "ype_test_", "ype_live_"))
            or not orden_firma):
        return jsonify({"ok": False, "error": "La sesión o el carrito no son válidos"}), 400

    try:
        productos, subtotal, delivery, total = _datos_checkout(items)
        orden = _COTIZACIONES.loads(orden_firma, max_age=1800)
        if (orden.get("email") != email or orden.get("amount") != int(total * 100)
                or any(orden.get(campo) != valor for campo, valor in cliente.items())
                or not orden.get("id", "").startswith(("ord_test_", "ord_live_"))):
            raise ValueError("La orden no corresponde a esta compra")
    except (BadSignature, SignatureExpired, KeyError, InvalidOperation, TypeError, ValueError):
        return jsonify({"ok": False, "error": "El carrito cambió o la cotización venció. Actualiza e intenta de nuevo"}), 400

    if token.startswith(("ype_test_", "ype_live_")) and int(total * 100) > 200000:
        return jsonify({"ok": False, "error": "Yape permite pagos de hasta S/ 2,000"}), 400

    cuotas = body.get("installments")
    if cuotas not in (None, "") and not token.startswith(("tkn_test_", "tkn_live_")):
        return jsonify({"ok": False, "error": "Las cuotas solo están disponibles para pagos con tarjeta"}), 400
    cargo = {"amount": int(total * 100), "currency_code": "PEN", "email": email, "source_id": token,
             "capture": True, "description": "Compra FarmaPulse",
             "metadata": {"dni": dni, "nombre": nombre, "order_id": orden["id"], "distrito": cliente["distrito"]}}
    if cuotas not in (None, ""):
        try:
            cuotas = int(cuotas)
            if cuotas < 2 or cuotas > 48:
                raise ValueError
            token_response = requests.get(f"https://api.culqi.com/v2/tokens/{token}",
                headers={"Authorization": f"Bearer {CULQI_SECRET_KEY}"}, timeout=10)
            token_data = token_response.json()
            permitidas = token_data.get("iin", {}).get("installments_allowed", [])
            if token_response.status_code >= 400 or cuotas not in permitidas:
                return jsonify({"ok": False, "error": "Las cuotas seleccionadas no están disponibles para esta tarjeta"}), 400
            cargo["installments"] = str(cuotas)
        except (TypeError, ValueError, requests.RequestException):
            return jsonify({"ok": False, "error": "No se pudieron validar las cuotas de la tarjeta"}), 400

    nombres = nombre.split(maxsplit=1)
    cargo["antifraud_details"] = {
        "first_name": nombres[0], "last_name": nombres[-1],
        "address": cliente["direccion"], "address_city": "Lima",
        "country_code": "PE", "phone_number": int(cliente["telefono"]), "email": email,
    }
    try:
        respuesta = requests.post("https://api.culqi.com/v2/charges",
            headers={"Authorization": f"Bearer {CULQI_SECRET_KEY}", "Content-Type": "application/json"},
            json=cargo, timeout=20)
        datos = respuesta.json()
    except (requests.RequestException, ValueError):
        return jsonify({"ok": False, "error": "No se pudo confirmar el pago con Culqi. Revisa tu estado de cuenta antes de reintentar"}), 502
    if (respuesta.status_code >= 400 or not isinstance(datos, dict)
            or datos.get("state", "").lower() not in {"exitosa", "captured", "paid"}
            or datos.get("currency") != "PEN"
            or datos.get("amount") != int(total * 100)):
        mensaje = (datos.get("user_message") or datos.get("merchant_message")) if isinstance(datos, dict) else None
        return jsonify({"ok": False, "error": mensaje or "Culqi no pudo procesar el pago"}), 402

    cargo_id = datos.get("id", "")
    try:
        _enviar_comprobante(email, nombre, dni, cliente, productos, subtotal, delivery, total, cargo_id)
    except (smtplib.SMTPException, OSError):
        app.logger.exception("El pago %s fue exitoso, pero falló el envío del comprobante", cargo_id)
        return jsonify({"ok": True, "pago_confirmado": True, "comprobante_enviado": False,
                        "mensaje": "Pago aprobado; no se pudo enviar el comprobante por correo. Contacta a soporte.", "cargo_id": cargo_id})
    return jsonify({"ok": True, "pago_confirmado": True, "comprobante_enviado": True, "cargo_id": cargo_id})


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
    for producto in resultados_ordenados:
        if fuente != "farmacias":
            continue
        cotizacion = {
            "medicamento": producto["medicamento"],
            "farmacia": producto["farmacia"],
            "presentacion": producto.get("presentacion") or "presentación única",
            "precio": str(Decimal(str(producto.get("precio_empaque") or producto["precio_unitario"])).quantize(Decimal("0.01"))),
        }
        producto["cotizacion"] = _COTIZACIONES.dumps(cotizacion)

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
