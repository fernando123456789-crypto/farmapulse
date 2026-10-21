"""DAO de listas de receta ("Mi Receta").

Concentra todo el acceso a la tabla `listas_recetas`. Cada llamada usa el token
del usuario (no la clave de servicio), así las políticas RLS de Supabase siguen
aplicando. Si no hay proyecto Supabase configurado, usa memoria local.
"""

from __future__ import annotations

from typing import Any

import requests


class RecetaDAOError(RuntimeError):
    """Supabase no respondió o rechazó la operación sobre listas_recetas."""


class RecetaDAO:
    def __init__(self, base_url: str | None = None, api_key: str | None = None,
                 memoria: list[dict] | None = None, timeout: int = 8, session: Any = None):
        self._base_url = (base_url or "").rstrip("/")
        self._api_key = api_key or ""
        self._memoria = memoria if memoria is not None else []
        self._timeout = timeout
        self._http = session or requests

    @property
    def usa_supabase(self) -> bool:
        return bool(self._base_url and self._api_key and "tu-proyecto" not in self._base_url)

    def _endpoint(self) -> str:
        return f"{self._base_url}/rest/v1/listas_recetas"

    def _headers(self, access_token: str | None) -> dict:
        headers = {"apikey": self._api_key, "Content-Type": "application/json"}
        if access_token:
            headers["Authorization"] = f"Bearer {access_token}"
        return headers

    def guardar(self, registro: dict, access_token: str | None = None) -> tuple[str, Any]:
        if not self.usa_supabase:
            self._memoria.append(registro)
            return "memoria_local", registro
        try:
            respuesta = self._http.post(
                self._endpoint(),
                headers={**self._headers(access_token), "Prefer": "return=representation"},
                json=registro, timeout=self._timeout,
            )
            respuesta.raise_for_status()
            return "supabase", respuesta.json()
        except (requests.RequestException, ValueError) as error:
            raise RecetaDAOError("No se pudo guardar la receta") from error

    def listar_por_usuario(self, usuario_id: str, access_token: str | None = None,
                           limite: int = 100) -> tuple[str, Any]:
        if not self.usa_supabase:
            return "memoria_local", [r for r in self._memoria if r["usuario_id"] == usuario_id]
        try:
            respuesta = self._http.get(
                self._endpoint(), headers=self._headers(access_token),
                params={"select": "*", "usuario_id": f"eq.{usuario_id}",
                        "order": "creado_en.desc", "limit": str(limite)},
                timeout=self._timeout,
            )
            respuesta.raise_for_status()
            return "supabase", respuesta.json()
        except (requests.RequestException, ValueError) as error:
            raise RecetaDAOError("No se pudo consultar el historial") from error
