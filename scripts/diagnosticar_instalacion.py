"""Compruebo una instalación local sin mostrar credenciales ni hacer llamadas externas."""

import os
from pathlib import Path

from dotenv import dotenv_values


ROOT = Path(__file__).resolve().parents[1]
GROUPS = {
    "Inicio de la app": ("SECRET_KEY",),
    "Inicio de sesión": ("SUPABASE_URL", "SUPABASE_KEY"),
    "Tarjeta y comprobante": (
        "MERCADO_PAGO_PUBLIC_KEY", "MERCADO_PAGO_ACCESS_TOKEN",
        "MAIL_HOST", "MAIL_USERNAME", "MAIL_PASSWORD",
    ),
    "Validación del DNI al pagar": ("RENIEC_TOKEN",),
}


def diagnose(config, root=ROOT):
    issues = []
    for label, names in GROUPS.items():
        missing = [name for name in names if not str(config.get(name) or "").strip()]
        if missing:
            issues.append(f"{label}: falta configurar " + ", ".join(missing))
    cert, key = config.get("LOCAL_HTTPS_CERT"), config.get("LOCAL_HTTPS_KEY")
    if not cert or not key:
        issues.append("HTTPS local: ejecuta scripts/configurar_https_local.ps1 en este equipo")
    elif not (root / cert).is_file() or not (root / key).is_file():
        issues.append("HTTPS local: faltan los archivos del certificado de este equipo; genera uno nuevo")
    try:
        if not 1 <= int(config.get("MAIL_PORT") or "587") <= 65535:
            raise ValueError
    except (ValueError, TypeError):
        issues.append("Correo: MAIL_PORT debe ser un puerto válido")
    return issues


def main():
    config = {**dotenv_values(ROOT / ".env"), **os.environ}
    issues = diagnose(config)
    print("Diagnóstico de instalación FarmaPulse (sin mostrar valores privados)")
    if not (ROOT / ".env").is_file():
        print("No existe .env local. Copia .env.example a .env y configura sus valores privados.")
    for issue in issues:
        print("- " + issue)
    if issues:
        print("Reinicia python app.py después de configurar el entorno.")
        return 1
    print("La configuración básica está presente. Abre https://127.0.0.1:5443/comparador.")
    print("Si los campos no aparecen, comprueba el certificado, el aviso del checkout y el acceso a sdk.mercadopago.com.")
    print("Este diagnóstico no verifica credenciales con los proveedores ni realiza cobros o envíos de correo.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
