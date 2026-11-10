"""Almacenamiento local SQLite (un archivo por instalación = un usuario).

Tablas:
  config             → ajustes de cálculo (core.calculator.Config) y preferencias no secretas
  days               → un documento JSON por fecha AAAA-MM-DD (modelo de reloj-de-jornada.md)
  workera_events     → cada correo Workera procesado (marcas por checksum, alertas ALERTA-<fecha>)
  workera_overrides  → correcciones manuales del usuario sobre el rol de una marca
  imap_seen          → UIDs IMAP ya procesados (por cuenta y carpeta)
  meta               → versión de esquema, última sincronización, etc.

Las credenciales NO se guardan aquí (ver services/auth.py).
"""
from __future__ import annotations

import json
import os
import sqlite3
import threading
from dataclasses import asdict
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Callable, Iterable, Optional

from core.calculator import Config, Day, to_date
from services.attendance_resolver import Marca, ResolucionDia
from services.workera_parser import AlertaWorkera, EventoAlerta, MarcacionWorkera

SCHEMA_VERSION = 1
NOMBRE_DB = "reloj_jornada.sqlite3"

_ESQUEMA = """
CREATE TABLE IF NOT EXISTS config (clave TEXT PRIMARY KEY, valor TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS days (
    fecha TEXT PRIMARY KEY,
    doc TEXT NOT NULL,
    actualizado TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS workera_events (
    checksum TEXT PRIMARY KEY,
    tipo_correo TEXT NOT NULL,          -- A (marcación) | B (alerta)
    fecha TEXT NOT NULL,
    hora TEXT,
    tipo_declarado TEXT,
    rol_asignado TEXT,
    metodo_asignacion TEXT,
    badge TEXT,
    estado TEXT,
    rut TEXT,
    payload TEXT NOT NULL,              -- JSON con todos los campos parseados
    raw_text TEXT,
    message_uid TEXT,
    recibido_en TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_events_fecha ON workera_events(fecha);
CREATE TABLE IF NOT EXISTS workera_overrides (
    fecha TEXT NOT NULL,
    checksum TEXT NOT NULL,
    rol TEXT NOT NULL,
    PRIMARY KEY (fecha, checksum)
);
CREATE TABLE IF NOT EXISTS imap_seen (
    cuenta TEXT NOT NULL,
    carpeta TEXT NOT NULL,
    uid TEXT NOT NULL,
    visto_en TEXT NOT NULL,
    PRIMARY KEY (cuenta, carpeta, uid)
);
CREATE TABLE IF NOT EXISTS meta (clave TEXT PRIMARY KEY, valor TEXT);
"""


def ruta_por_defecto() -> Path:
    """FLET_APP_STORAGE_DATA en la app empaquetada (Android/macOS); ~/.reloj_jornada en desarrollo."""
    base = os.getenv("FLET_APP_STORAGE_DATA") or str(Path.home() / ".reloj_jornada")
    Path(base).mkdir(parents=True, exist_ok=True)
    return Path(base) / NOMBRE_DB


def _ahora() -> str:
    return datetime.now().isoformat(timespec="seconds")


class Database:
    """`ruta=":memory:"` + `exportar()/importar()` se usa en la PWA (el navegador no tiene disco:
    la app guarda una copia de la base en el almacenamiento local después de cada cambio)."""

    def __init__(self, ruta: Optional[os.PathLike | str] = None, al_cambiar: Optional[Callable[[], None]] = None):
        self.ruta = str(ruta or ruta_por_defecto())
        self.al_cambiar = al_cambiar
        # Flet ejecuta los handlers en hilos distintos: una conexión + candado.
        self._conn = sqlite3.connect(self.ruta, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._lock = threading.RLock()
        self._crear_esquema()

    def _crear_esquema(self) -> None:
        with self._lock, self._conn:
            self._conn.executescript(_ESQUEMA)
            self._conn.execute("INSERT OR IGNORE INTO meta VALUES ('schema_version', ?)", (str(SCHEMA_VERSION),))

    def close(self) -> None:
        self._conn.close()

    def exportar(self) -> bytes:
        with self._lock:
            return self._conn.serialize()

    def importar(self, datos: bytes) -> None:
        with self._lock:
            self._conn.deserialize(datos)
        self._crear_esquema()

    def _notificar(self) -> None:
        if self.al_cambiar:
            self.al_cambiar()

    def _q(self, sql: str, params: Iterable = ()) -> list[sqlite3.Row]:
        with self._lock:
            return self._conn.execute(sql, tuple(params)).fetchall()

    def _x(self, sql: str, params: Iterable = ()) -> int:
        with self._lock, self._conn:
            n = self._conn.execute(sql, tuple(params)).rowcount
        self._notificar()
        return n

    # ------------------------------------------------------------------ meta / preferencias
    def get_meta(self, clave: str, defecto: Optional[str] = None) -> Optional[str]:
        filas = self._q("SELECT valor FROM meta WHERE clave = ?", (clave,))
        return filas[0]["valor"] if filas else defecto

    def set_meta(self, clave: str, valor: Optional[str]) -> None:
        self._x("INSERT INTO meta VALUES (?, ?) ON CONFLICT(clave) DO UPDATE SET valor = excluded.valor",
                (clave, valor))

    def get_pref(self, clave: str, defecto=None):
        filas = self._q("SELECT valor FROM config WHERE clave = ?", (clave,))
        return json.loads(filas[0]["valor"]) if filas else defecto

    def set_pref(self, clave: str, valor) -> None:
        self._x("INSERT INTO config VALUES (?, ?) ON CONFLICT(clave) DO UPDATE SET valor = excluded.valor",
                (clave, json.dumps(valor, ensure_ascii=False)))

    def get_config(self) -> Config:
        return Config.from_dict(self.get_pref("calculo", {}))

    def save_config(self, cfg: Config) -> None:
        self.set_pref("calculo", cfg.to_dict())

    # ------------------------------------------------------------------ días
    def get_day(self, fecha) -> Day:
        f = to_date(fecha)
        filas = self._q("SELECT doc FROM days WHERE fecha = ?", (f.isoformat(),))
        return Day.from_dict(json.loads(filas[0]["doc"]), fecha=f) if filas else Day(fecha=f)

    def save_day(self, day: Day) -> None:
        doc = day.to_dict()
        doc.pop("fecha")
        self._x("INSERT INTO days VALUES (?, ?, ?) ON CONFLICT(fecha) DO UPDATE SET "
                "doc = excluded.doc, actualizado = excluded.actualizado",
                (day.fecha.isoformat(), json.dumps(doc, ensure_ascii=False), _ahora()))

    def days_between(self, desde, hasta) -> dict[date, Day]:
        filas = self._q("SELECT fecha, doc FROM days WHERE fecha BETWEEN ? AND ? ORDER BY fecha",
                        (to_date(desde).isoformat(), to_date(hasta).isoformat()))
        return {date.fromisoformat(r["fecha"]): Day.from_dict(json.loads(r["doc"]), fecha=r["fecha"])
                for r in filas}

    def days_week(self, fecha) -> dict[date, Day]:
        f = to_date(fecha)
        lunes = f - timedelta(days=f.weekday())
        return self.days_between(lunes, lunes + timedelta(days=6))

    def borrar_periodo(self, desde, hasta) -> int:
        d, h = to_date(desde).isoformat(), to_date(hasta).isoformat()
        with self._lock, self._conn:
            n = self._conn.execute("DELETE FROM days WHERE fecha BETWEEN ? AND ?", (d, h)).rowcount
            self._conn.execute("DELETE FROM workera_events WHERE fecha BETWEEN ? AND ?", (d, h))
            self._conn.execute("DELETE FROM workera_overrides WHERE fecha BETWEEN ? AND ?", (d, h))
        self._notificar()
        return n

    # ------------------------------------------------------------------ eventos Workera
    def guardar_marcacion(self, m: MarcacionWorkera, uid: Optional[str] = None) -> bool:
        """Inserta la marca si su checksum es nuevo. Devuelve True si era nueva (idempotente)."""
        payload = asdict(m)
        payload.pop("raw_text", None)
        return self._x(
            "INSERT OR IGNORE INTO workera_events (checksum, tipo_correo, fecha, hora, tipo_declarado, "
            "estado, rut, payload, raw_text, message_uid, recibido_en) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (m.checksum, "A", m.fecha, m.hora, m.tipo_marca_declarado, m.estado, m.rut_trabajador,
             json.dumps(payload, ensure_ascii=False), m.raw_text, uid, _ahora()),
        ) == 1

    def guardar_alerta(self, a: AlertaWorkera, uid: Optional[str] = None) -> bool:
        """Guarda la alerta del día; una alerta más reciente del mismo día reemplaza a la anterior."""
        previa = self.get_alerta(a.fecha)
        if previa and previa.hora_alerta and a.hora_alerta and previa.hora_alerta > a.hora_alerta:
            return False
        payload = asdict(a)
        payload.pop("raw_text", None)
        self._x(
            "INSERT INTO workera_events (checksum, tipo_correo, fecha, rut, payload, raw_text, message_uid, "
            "recibido_en) VALUES (?,?,?,?,?,?,?,?) ON CONFLICT(checksum) DO UPDATE SET payload = excluded.payload, "
            "raw_text = excluded.raw_text, message_uid = excluded.message_uid, recibido_en = excluded.recibido_en",
            (a.clave, "B", a.fecha, a.run_trabajador, json.dumps(payload, ensure_ascii=False), a.raw_text, uid, _ahora()),
        )
        if previa is None:
            return True
        sin_texto = lambda x: {k: v for k, v in asdict(x).items() if k != "raw_text"}  # noqa: E731
        return sin_texto(previa) != sin_texto(a)

    def get_marcas(self, fecha) -> list[Marca]:
        filas = self._q("SELECT checksum, fecha, hora, tipo_declarado, estado FROM workera_events "
                        "WHERE tipo_correo = 'A' AND fecha = ? ORDER BY hora", (to_date(fecha).isoformat(),))
        return [Marca(r["checksum"], r["fecha"], r["hora"], r["tipo_declarado"],
                      activa=not r["estado"] or r["estado"].lower() == "activo") for r in filas]

    def get_alerta(self, fecha) -> Optional[AlertaWorkera]:
        filas = self._q("SELECT payload FROM workera_events WHERE tipo_correo = 'B' AND fecha = ?",
                        (to_date(fecha).isoformat(),))
        if not filas:
            return None
        d = json.loads(filas[0]["payload"])
        d["alertas_detectadas"] = [EventoAlerta(**e) for e in d.get("alertas_detectadas", [])]
        return AlertaWorkera(**d)

    def fechas_con_eventos(self) -> list[str]:
        return [r["fecha"] for r in self._q("SELECT DISTINCT fecha FROM workera_events ORDER BY fecha")]

    def eventos(self, fecha) -> list[sqlite3.Row]:
        return self._q("SELECT * FROM workera_events WHERE fecha = ? ORDER BY tipo_correo, hora",
                       (to_date(fecha).isoformat(),))

    def actualizar_asignaciones(self, res: ResolucionDia) -> None:
        with self._lock, self._conn:
            for a in res.asignaciones:
                self._conn.execute(
                    "UPDATE workera_events SET rol_asignado = ?, metodo_asignacion = ?, badge = ? WHERE checksum = ?",
                    (a.rol, a.metodo, a.badge, a.checksum))
        self._notificar()

    # ------------------------------------------------------------------ overrides
    def get_overrides(self, fecha) -> dict[str, str]:
        return {r["checksum"]: r["rol"] for r in self._q(
            "SELECT checksum, rol FROM workera_overrides WHERE fecha = ?", (to_date(fecha).isoformat(),))}

    def set_overrides(self, fecha, overrides: dict[str, str]) -> None:
        f = to_date(fecha).isoformat()
        with self._lock, self._conn:
            self._conn.execute("DELETE FROM workera_overrides WHERE fecha = ?", (f,))
            self._conn.executemany("INSERT INTO workera_overrides VALUES (?, ?, ?)",
                                   [(f, c, r) for c, r in overrides.items()])
        self._notificar()

    # ------------------------------------------------------------------ IMAP
    def uids_vistos(self, cuenta: str, carpeta: str) -> set[str]:
        return {r["uid"] for r in self._q("SELECT uid FROM imap_seen WHERE cuenta = ? AND carpeta = ?",
                                          (cuenta.lower(), carpeta))}

    def marcar_uid_visto(self, cuenta: str, carpeta: str, uid: str) -> None:
        self._x("INSERT OR IGNORE INTO imap_seen VALUES (?, ?, ?, ?)", (cuenta.lower(), carpeta, uid, _ahora()))

    def olvidar_uids(self) -> None:
        self._x("DELETE FROM imap_seen")
