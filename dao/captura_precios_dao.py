"""Acceso a datos de catálogo, precios y ejecuciones de scraping."""

from __future__ import annotations

from typing import Any


class CapturaPreciosDAO:
    def __init__(self, supabase_client: Any):
        self._supabase = supabase_client
        self._cache_farmacias: dict[str, int] = {}
        self._cache_presentaciones: dict[str, int] = {}

    def obtener_watchlist(self) -> list[dict]:
        resultado = self._supabase.table("medicamentos").select("id, nombre").execute()
        return resultado.data or []

    def obtener_o_crear_farmacia_id(self, nombre: str) -> int:
        if nombre in self._cache_farmacias:
            return self._cache_farmacias[nombre]

        resultado = self._supabase.table("farmacias").select("id").eq("nombre", nombre).execute()
        if resultado.data:
            farmacia_id = resultado.data[0]["id"]
        else:
            insertado = self._supabase.table("farmacias").insert({"nombre": nombre}).execute()
            farmacia_id = insertado.data[0]["id"]

        self._cache_farmacias[nombre] = farmacia_id
        return farmacia_id

    def obtener_o_crear_presentacion_id(self, descripcion: str) -> int | None:
        descripcion = (descripcion or "").strip()
        if not descripcion:
            return None
        if descripcion in self._cache_presentaciones:
            return self._cache_presentaciones[descripcion]

        resultado = (
            self._supabase.table("presentaciones")
            .select("id")
            .eq("descripcion", descripcion)
            .execute()
        )
        if resultado.data:
            presentacion_id = resultado.data[0]["id"]
        else:
            insertado = self._supabase.table("presentaciones").insert(
                {"descripcion": descripcion}
            ).execute()
            presentacion_id = insertado.data[0]["id"]

        self._cache_presentaciones[descripcion] = presentacion_id
        return presentacion_id

    def insertar_precio(self, fila: dict) -> None:
        self._supabase.table("precios").insert(fila).execute()

    def registrar_scrape(self, registro: dict) -> None:
        self._supabase.table("scrapes_log").insert(registro).execute()