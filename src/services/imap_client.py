"""Descarga de correos Workera por IMAP (Gmail, SSL 993), en modo solo lectura.

Las credenciales NUNCA se definen aquí: llegan desde services/auth.py (keyring / almacén cifrado).
"""
from __future__ import annotations

import imaplib
from dataclasses import dataclass
from datetime import date
from typing import Callable, Iterable, Optional

from services.workera_parser import WORKERA_SENDER

GMAIL_IMAP_HOST = "imap.gmail.com"
IMAP_SSL_PORT = 993
CARPETA_POR_DEFECTO = "02_Reloj_Control"
_MESES_IMAP = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")


class ImapError(RuntimeError):
    pass


@dataclass
class ImapSettings:
    usuario: str
    app_password: str
    carpeta: str = CARPETA_POR_DEFECTO
    remitente: str = WORKERA_SENDER
    host: str = GMAIL_IMAP_HOST
    port: int = IMAP_SSL_PORT

    def __repr__(self) -> str:   # nunca exponer la contraseña en logs
        return f"ImapSettings(usuario={self.usuario!r}, carpeta={self.carpeta!r}, host={self.host!r})"


def fecha_imap(d: date) -> str:
    """Formato SINCE de IMAP (09-Nov-2026) sin depender del locale del sistema."""
    return f"{d.day:02d}-{_MESES_IMAP[d.month - 1]}-{d.year}"


def _conectar_ssl(host: str, port: int) -> imaplib.IMAP4:
    import ssl  # diferido: en la PWA (Pyodide) ssl no está cargado y no se usa IMAP
    return imaplib.IMAP4_SSL(host, port, ssl_context=ssl.create_default_context())


def criterio_remitente(remitente: str) -> str:
    """Workera escribe desde varias direcciones (notificaciones@ para marcas, info@ para alertas):
    se busca por dominio. IMAP FROM hace coincidencia por subcadena."""
    return (remitente or WORKERA_SENDER).split("@")[-1].strip().lower()


def _quote(nombre: str) -> str:
    return '"' + nombre.replace("\\", "\\\\").replace('"', '\\"') + '"'


class WorkeraMailbox:
    def __init__(self, settings: ImapSettings,
                 imap_factory: Optional[Callable[..., imaplib.IMAP4]] = None):
        self.settings = settings
        self._factory = imap_factory or _conectar_ssl

    def _seleccionar(self, conn) -> str:
        for carpeta in dict.fromkeys([self.settings.carpeta, "INBOX"]):
            typ, _ = conn.select(_quote(carpeta), readonly=True)
            if typ == "OK":
                return carpeta
        raise ImapError(f"No se pudo abrir la carpeta {self.settings.carpeta!r} ni INBOX")

    def descargar(self, desde: Optional[date] = None,
                  uids_vistos: Iterable[str] = ()) -> list[tuple[str, bytes]]:
        """Devuelve [(uid, mensaje_rfc822)] de los correos de Workera no vistos.
        No marca como leído (BODY.PEEK) ni modifica el buzón."""
        vistos = set(uids_vistos)
        s = self.settings
        conn = self._factory(s.host, s.port)
        try:
            conn.login(s.usuario, s.app_password.replace(" ", ""))
            self._seleccionar(conn)
            criterios = ["FROM", _quote(criterio_remitente(s.remitente))]
            if desde:
                criterios += ["SINCE", fecha_imap(desde)]
            typ, data = conn.uid("SEARCH", None, *criterios)
            if typ != "OK":
                raise ImapError("La búsqueda IMAP falló")
            uids = [u.decode() for u in (data[0] or b"").split()]
            salida = []
            for uid in uids:
                if uid in vistos:
                    continue
                typ, partes = conn.uid("FETCH", uid, "(BODY.PEEK[])")
                if typ != "OK":
                    continue
                for parte in partes:
                    if isinstance(parte, tuple) and len(parte) == 2:
                        salida.append((uid, parte[1]))
                        break
            return salida
        except imaplib.IMAP4.error as exc:
            raise ImapError(f"Error IMAP: {exc}") from exc
        finally:
            try:
                conn.logout()
            except Exception:
                pass
