"""Avisos push con la app cerrada vía ntfy (https://ntfy.sh), en Android y iPhone.

Cuando se conoce la hora de salida (al marcar ingreso, cambiar el plan o sincronizar Workera),
se programa en el servidor ntfy un mensaje con `At:` = salida − N minutos. El teléfono, suscrito al
canal con la app gratuita «ntfy», suena aunque Reloj de Jornada esté cerrada.

- Cada día usa un sequence ID fijo (`salida-AAAAMMDD`): publicar de nuevo REEMPLAZA el aviso
  programado y `DELETE /<canal>/<seq>` lo cancela (p. ej. al marcar la salida).
- El canal es un nombre aleatorio largo: quien lo conozca puede leer los avisos, por eso nunca se
  comparte ni va en el código. El mensaje solo lleva la hora de salida.
- ntfy.sh acepta programar entre 10 s y 3 días hacia adelante.
"""
from __future__ import annotations

import asyncio
import re
import secrets
import sys
import time as _time
from dataclasses import asdict, dataclass
from datetime import date, datetime, timedelta
from typing import Optional, Protocol

SERVIDOR_POR_DEFECTO = "https://ntfy.sh"
MIN_ANTICIPACION_S = 10
MAX_ANTICIPACION_S = 3 * 24 * 3600
_RE_CANAL = re.compile(r"[A-Za-z0-9_-]{1,64}")


class PushError(RuntimeError):
    pass


def generar_canal() -> str:
    return "reloj-" + secrets.token_hex(12)


@dataclass
class PushConfig:
    activo: bool = False
    servidor: str = SERVIDOR_POR_DEFECTO
    canal: str = ""

    @classmethod
    def from_dict(cls, d: Optional[dict]) -> "PushConfig":
        d = d or {}
        return cls(**{k: v for k, v in d.items() if k in ("activo", "servidor", "canal")})

    def to_dict(self) -> dict:
        return asdict(self)

    @property
    def listo(self) -> bool:
        return self.activo and bool(self.canal) and bool(_RE_CANAL.fullmatch(self.canal))

    @property
    def url_canal(self) -> str:
        return f"{self.servidor.rstrip('/')}/{self.canal}"


# ----------------------------------------------------------------------------- transporte HTTP
class Transporte(Protocol):
    async def __call__(self, metodo: str, url: str, headers: dict[str, str], cuerpo: bytes) -> int: ...


async def _urllib(metodo: str, url: str, headers: dict[str, str], cuerpo: bytes) -> int:
    import urllib.error
    import urllib.request

    def hacer() -> int:
        req = urllib.request.Request(url, data=cuerpo or None, headers=headers, method=metodo)
        try:
            with urllib.request.urlopen(req, timeout=15) as r:
                return r.status
        except urllib.error.HTTPError as e:
            return e.code
    return await asyncio.to_thread(hacer)


async def _pyodide(metodo: str, url: str, headers: dict[str, str], cuerpo: bytes) -> int:
    from pyodide.http import pyfetch  # type: ignore[import-not-found]
    r = await pyfetch(url, method=metodo, headers=headers, body=cuerpo.decode("utf-8") if cuerpo else None)
    return r.status


def transporte_por_defecto() -> Transporte:
    return _pyodide if sys.platform == "emscripten" else _urllib


# ----------------------------------------------------------------------------- notificador
def seq_salida(fecha: date) -> str:
    return f"salida-{fecha:%Y%m%d}"


def instante_local(fecha: date, segundos: int) -> float:
    """Fecha + segundos desde medianoche (hora local del dispositivo) → timestamp Unix."""
    return (datetime.combine(fecha, datetime.min.time()) + timedelta(seconds=segundos)).timestamp()


class PushNotifier:
    def __init__(self, cfg: PushConfig, transporte: Optional[Transporte] = None,
                 reloj=_time.time):
        self.cfg = cfg
        self._enviar = transporte or transporte_por_defecto()
        self._reloj = reloj

    async def _req(self, metodo: str, ruta: str, headers: Optional[dict] = None, cuerpo: str = "") -> int:
        if not self.cfg.canal or not _RE_CANAL.fullmatch(self.cfg.canal):
            raise PushError("Canal de avisos inválido")
        url = self.cfg.url_canal + (f"/{ruta}" if ruta else "")
        try:
            status = await self._enviar(metodo, url, headers or {}, cuerpo.encode("utf-8"))
        except Exception as exc:  # red caída, DNS, etc.
            raise PushError(f"No se pudo contactar a {self.cfg.servidor}: {exc}") from exc
        if status >= 400 and not (metodo == "DELETE" and status == 404):
            raise PushError(f"ntfy respondió {status}")
        return status

    async def programar_salida(self, fecha: date, salida_s: int, minutos_antes: int) -> Optional[float]:
        """Programa (o reprograma) el aviso del día. Devuelve el instante programado o None si
        ya pasó / está fuera del rango que acepta ntfy (en ese caso cancela el anterior)."""
        cuando = instante_local(fecha, salida_s - minutos_antes * 60)
        falta = cuando - self._reloj()
        if not (MIN_ANTICIPACION_S <= falta <= MAX_ANTICIPACION_S):
            await self.cancelar_salida(fecha)
            return None
        hh = f"{salida_s // 3600 % 24:02d}:{salida_s // 60 % 60:02d}"
        await self._req("POST", seq_salida(fecha), {
            "At": str(int(cuando)),
            "Title": "Reloj de Jornada",
            "Priority": "high",
            "Tags": "alarm_clock",
        }, f"Tu salida es a las {hh} (en {minutos_antes} min).")
        return cuando

    async def cancelar_salida(self, fecha: date) -> None:
        await self._req("DELETE", seq_salida(fecha))

    async def prueba(self) -> None:
        await self._req("POST", "", {"Title": "Reloj de Jornada", "Priority": "high", "Tags": "white_check_mark"},
                        "Prueba: si ves esto con la app cerrada, los avisos de salida funcionan.")
