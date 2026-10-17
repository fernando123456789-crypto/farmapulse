"""HTTPS para desarrollo local; los certificados permanecen fuera de Git."""

import os
import ssl
from pathlib import Path
from threading import Thread
from urllib.parse import quote

from werkzeug.serving import make_server
from werkzeug.wrappers import Response


def redirect_to_https(port):
    def redirect(environ, start_response):
        if environ.get("REQUEST_METHOD") not in {"GET", "HEAD"}:
            response = Response("Abre la página con HTTPS antes de continuar.", status=426)
        else:
            path = quote(environ.get("PATH_INFO", "/"), safe="/:@")
            query = environ.get("QUERY_STRING", "")
            target = f"https://127.0.0.1:{port}{path}" + (f"?{query}" if query else "")
            response = Response(status=307, headers={"Location": target, "Cache-Control": "no-store"})
        return response(environ, start_response)
    return redirect


def run_local_server(app):
    cert, key = os.getenv("LOCAL_HTTPS_CERT", ""), os.getenv("LOCAL_HTTPS_KEY", "")
    if not cert and not key:
        app.run(host="127.0.0.1", port=5000, debug=os.getenv("FLASK_ENV") == "development")
        return
    if not cert or not key:
        raise ValueError("Configura LOCAL_HTTPS_CERT y LOCAL_HTTPS_KEY para usar HTTPS local")
    base = Path(__file__).resolve().parent
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.minimum_version = ssl.TLSVersion.TLSv1_2
    context.load_cert_chain(base / cert, base / key)
    port = int(os.getenv("LOCAL_HTTPS_PORT", "5443"))
    if not 1024 <= port <= 65535 or port == 5000:
        raise ValueError("LOCAL_HTTPS_PORT debe estar entre 1024 y 65535 y ser distinto de 5000")
    with make_server("127.0.0.1", 5000, redirect_to_https(port)) as redirect_server:
        thread = Thread(target=redirect_server.serve_forever, daemon=True)
        thread.start()
        try:
            app.run(host="127.0.0.1", port=port, ssl_context=context, debug=False, use_reloader=False)
        finally:
            redirect_server.shutdown()
            thread.join(timeout=5)
