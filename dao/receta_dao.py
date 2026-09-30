"""Persistencia de listas de receta en Supabase con fallback en memoria."""

from __future__ import annotations

import logging
from typing import Any


logger = logging.getLogger(__name__)


class RecetaDAO:
    def __init__(self, supabase_client: Any = None, memoria: list[dict] | None = None):
        self._supabase = supabase_client
        self._memoria = memoria if memoria is not None else []

    def guardar(self, registro: dict) -> tuple[str, Any]:
        if self._supabase is not None:
            try:
                resultado = (
                    self._supabase.table("listas_recetas")
                    .insert(registro)
                    .execute()
                )
                return "supabase", resultado.data
            except Exception:
                logger.exception("Error al guardar receta en Supabase")

        self._memoria.append(registro)
        return "memoria_local", registro

    def listar_por_usuario(self, usuario_id: str) -> tuple[str, Any]:
        if self._supabase is not None:
            try:
                resultado = (
                    self._supabase.table("listas_recetas")
                    .select("*")
                    .eq("usuario_id", usuario_id)
                    .order("creado_en", desc=True)
                    .execute()
                )
                return "supabase", resultado.data
            except Exception:
                logger.exception("Error al leer historial de recetas en Supabase")

        historial = [
            registro for registro in self._memoria
            if registro["usuario_id"] == usuario_id
        ]
        return "memoria_local", historial