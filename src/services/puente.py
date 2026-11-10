"""Cliente del Puente Google (tools/workera_gmail_bridge.gs), para Android y la PWA de iPhone.

El puente corre en la cuenta de Google de cada usuario y expone una URL
`https://script.google.com/macros/s/<id>/exec` protegida con una clave. Acciones:
  ping · correos (RFC 822 en base64url) · config (aviso en segundo plano) · salida · respaldo_subir/bajar

Peticiones «simples» (GET, o POST text/plain) para que el navegador no haga preflight CORS,
que Apps Script no soporta. Apps Script responde con una redirección a googleusercontent.com que
urllib y fetch siguen solos.
"""
from __future__ import annotations

import asyncio
import base64
import json
import re
import sys
import zlib
from dataclasses import asdict, dataclass
from datetime import date
from typing import Awaitable, Callable, Optional
from urllib.parse import urlencode

from core.calculator import Config
from services.push_notifier import PushConfig

RE_URL = re.compile(r"https://script\.google\.com/macros/s/[A-Za-z0-9_-]+/exec")

Http = Callable[[str, str, Optional[str]], Awaitable[tuple[int, str]]]


class PuenteError(RuntimeError):
    pass


@dataclass
class PuenteConfig:
    url: str = ""
    clave: str = ""
    rut: str = ""

    @classmethod
    def from_dict(cls, d: Optional[dict]) -> "PuenteConfig":
        d = d or {}
        return cls(**{k: str(v or "") for k, v in d.items() if k in ("url", "clave", "rut")})

    def to_dict(self) -> dict:
        return asdict(self)

    @property
    def listo(self) -> bool:
        return bool(RE_URL.fullmatch(self.url.strip())) and len(self.clave.strip()) >= 16

    def errores(self) -> list[str]:
        e = []
        if not RE_URL.fullmatch(self.url.strip()):
            e.append("La URL debe ser https://script.google.com/macros/s/…/exec")
        if len(self.clave.strip()) < 16:
            e.append("Pega la clave que mostró `setup` en Apps Script")
        return e

    def __repr__(self) -> str:   # la clave nunca en logs
        return f"PuenteConfig(url={self.url[:45]!r}…, rut={self.rut!r})"


# ----------------------------------------------------------------------------- HTTP
async def _http_urllib(metodo: str, url: str, cuerpo: Optional[str]) -> tuple[int, str]:
    import urllib.error
    import urllib.request

    def hacer() -> tuple[int, str]:
        datos = cuerpo.encode("utf-8") if cuerpo is not None else None
        req = urllib.request.Request(url, data=datos, method=metodo,
                                     headers={"Content-Type": "text/plain;charset=utf-8"} if datos else {})
        try:
            with urllib.request.urlopen(req, timeout=120) as r:
                return r.status, r.read().decode("utf-8", "replace")
        except urllib.error.HTTPError as e:
            return e.code, e.read().decode("utf-8", "replace")
    return await asyncio.to_thread(hacer)


async def _http_pyodide(metodo: str, url: str, cuerpo: Optional[str]) -> tuple[int, str]:
    from pyodide.http import pyfetch  # type: ignore[import-not-found]
    r = await pyfetch(url, method=metodo, body=cuerpo) if cuerpo is not None else await pyfetch(url, method=metodo)
    return r.status, await r.string()


def http_por_defecto() -> Http:
    return _http_pyodide if sys.platform == "emscripten" else _http_urllib


def decidir_respaldo_auto(propio: Optional[str], remoto: Optional[str], dias_locales: int) -> str:
    """Respaldo automático entre varios dispositivos de la misma persona (gana el último que sube):
      "omitir"    → base local vacía: subirla borraría el respaldo bueno
      "conflicto" → en la nube hay un respaldo más nuevo que el último que subió este dispositivo
                    (lo subió otro): no se pisa; el usuario decide (Restaurar o Respaldar ahora)
      "subir"     → normal
    Las fechas son ISO 8601 en UTC (toISOString de Apps Script), comparables como texto."""
    if dias_locales <= 0:
        return "omitir"
    if remoto and (not propio or remoto > propio):
        return "conflicto"
    return "subir"


def _b64url_a_bytes(texto: str) -> bytes:
    return base64.urlsafe_b64decode(texto + "=" * (-len(texto) % 4))


# ----------------------------------------------------------------------------- cliente
class PuenteGoogle:
    def __init__(self, cfg: PuenteConfig, http: Optional[Http] = None):
        self.cfg = cfg
        self._http = http or http_por_defecto()

    async def _llamar(self, accion: str, params: Optional[dict] = None, cuerpo: Optional[str] = None) -> dict:
        if not self.cfg.listo:
            raise PuenteError("Configura la URL y la clave del Puente Google en Ajustes")
        q = urlencode({"accion": accion, "token": self.cfg.clave.strip(), **(params or {})})
        try:
            status, texto = await self._http("POST" if cuerpo is not None else "GET",
                                             f"{self.cfg.url.strip()}?{q}", cuerpo)
        except Exception as exc:
            raise PuenteError(f"No se pudo contactar al Puente Google: {exc}") from exc
        if status >= 400:
            raise PuenteError(f"El Puente Google respondió {status}. ¿Publicaste la app web con acceso «Cualquier usuario»?")
        try:
            datos = json.loads(texto)
        except ValueError:
            raise PuenteError("El Puente Google no respondió JSON (revisa que la URL sea la de la implementación /exec)") from None
        if not datos.get("ok"):
            raise PuenteError(f"Puente Google: {datos.get('error', 'error desconocido')}")
        return datos

    async def ping(self) -> dict:
        return await self._llamar("ping")

    async def correos(self, desde_epoch: Optional[int] = None, dias: int = 45) -> list[tuple[str, bytes]]:
        params = {"desde": int(desde_epoch)} if desde_epoch else {"dias": dias}
        datos = await self._llamar("correos", params)
        return [(f"g{c['id']}", _b64url_a_bytes(c["raw"])) for c in datos.get("correos", [])]

    async def configurar(self, push: PushConfig, cfg: Config) -> None:
        await self._llamar("config", {
            "activo": "1" if push.listo else "0", "canal": push.canal, "servidor": push.servidor,
            "jornada_s": cfg.jornada_s, "colacion_s": cfg.colacion_s, "aviso_min": cfg.aviso_salida_min,
            "dias": ",".join(str(d) for d in cfg.dias_laborales),
        })

    async def informar_salida(self, fecha: date, salida_s: Optional[int]) -> None:
        """La app ya programó (o canceló) el aviso de hoy con el plan real: el puente no lo pisa."""
        await self._llamar("salida", {"fecha": fecha.isoformat(), "salida_s": "" if salida_s is None else salida_s})

    async def subir_respaldo(self, db_bytes: bytes) -> str:
        texto = base64.b64encode(zlib.compress(db_bytes, 9)).decode("ascii")
        return (await self._llamar("respaldo_subir", cuerpo=texto)).get("fecha", "")

    async def bajar_respaldo(self) -> tuple[Optional[bytes], Optional[str]]:
        datos = await self._llamar("respaldo_bajar")
        if not datos.get("datos"):
            return None, None
        return zlib.decompress(base64.b64decode(datos["datos"])), datos.get("fecha")
