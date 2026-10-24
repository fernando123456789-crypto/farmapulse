"""Importo el código desde una copia separada de la aplicación."""

import sys

from pruebas.application import application_root

sys.path.insert(0, str(application_root()))
