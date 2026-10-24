"""Localizo la copia externa de la app que uso en las pruebas unitarias."""

import os
from pathlib import Path


def application_root():
    location = os.getenv('FARMAPULSE_APP_ROOT', '').strip()
    configuration = Path(__file__).with_name('.env.pruebas')
    if not location and configuration.exists():
        for line in configuration.read_text(encoding='utf-8-sig').splitlines():
            name, separator, value = line.partition('=')
            if separator and name.strip() == 'FARMAPULSE_APP_ROOT':
                location = value.strip().strip('"').strip("'")
                break
    if not location:
        raise RuntimeError('Configuro FARMAPULSE_APP_ROOT con la ruta de una copia separada de FarmaPulse.')
    root = Path(location).expanduser().resolve()
    if not (root / 'security.py').is_file() or not (root / 'static/js/main.js').is_file():
        raise RuntimeError('Selecciono la raíz de la aplicación FarmaPulse en FARMAPULSE_APP_ROOT.')
    return root
