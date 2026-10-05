"""Política HTTP común a páginas, API, estáticos y errores."""
import json
import os
from pathlib import Path

from flask import jsonify, redirect, request, url_for
from werkzeug.middleware.proxy_fix import ProxyFix


def init_http_security(app):
    development = os.getenv('FLASK_ENV') == 'development'
    app.config.update(
        FORCE_HTTPS=not development,
        SESSION_COOKIE_SECURE=not development,
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE='Lax',
        MAX_CONTENT_LENGTH=64 * 1024,
    )
    # Render termina TLS y pasa HTTP al backend, inaccesible desde Internet.
    # Confiar solo en el esquema del último proxy de Render; no asumir su cadena de IP.
    render = os.getenv('RENDER') == 'true'
    hops = int(os.getenv('TRUSTED_PROXY_HOPS', '0'))
    proto_hops = int(os.getenv('TRUSTED_PROTO_HOPS', str(hops or (1 if render else 0))))
    if hops < 0:
        raise ValueError('TRUSTED_PROXY_HOPS debe ser mayor o igual a cero')
    if proto_hops < 0:
        raise ValueError('TRUSTED_PROTO_HOPS debe ser mayor o igual a cero')
    if hops or proto_hops:
        app.wsgi_app = ProxyFix(app.wsgi_app, x_for=hops, x_proto=proto_hops)

    manifest = json.loads(
        (Path(app.static_folder) / 'asset-integrity.json').read_text(encoding='utf-8')
    )
    app.jinja_env.globals['asset_integrity'] = lambda filename: manifest[filename]
    app.jinja_env.globals['asset_url'] = lambda filename: url_for(
        'static', filename=filename, v=manifest[filename].split('-', 1)[1]
    )

    @app.before_request
    def protect_transport_and_urls():
        # No reflejar una query sensible en Location; las API reciben datos por JSON.
        if request.path.startswith('/api/') and request.query_string:
            return jsonify(ok=False, error='Usa el cuerpo JSON; no envíes datos en la URL'), 400
        if app.config['FORCE_HTTPS'] and not request.is_secure:
            if request.method not in ('GET', 'HEAD'):
                return jsonify(ok=False, error='Se requiere HTTPS'), 400
            return redirect(request.url.replace('http://', 'https://', 1), code=308)

    @app.after_request
    def security_headers(response):
        response.headers['Content-Security-Policy'] = '; '.join([
            "default-src 'self'", "script-src 'self'", "style-src 'self'",
            "font-src 'self'", "connect-src 'self'",
            "img-src 'self' data: https://i.pravatar.cc https://images.unsplash.com",
            "object-src 'none'", "base-uri 'none'", "frame-ancestors 'none'",
            "form-action 'self'",
        ])
        response.headers['X-Frame-Options'] = 'DENY'
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['Referrer-Policy'] = 'no-referrer'
        if request.is_secure:
            response.headers['Strict-Transport-Security'] = 'max-age=31536000'
        if request.endpoint == 'static' and response.status_code == 200:
            response.headers['Cache-Control'] = 'public, max-age=0, must-revalidate'
        else:
            # Incluye HTML con token CSRF, sesiones, recetas y respuestas de error.
            response.headers['Cache-Control'] = 'no-store'
            response.headers['Pragma'] = 'no-cache'
        return response
