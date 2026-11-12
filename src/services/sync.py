"""Sincronización Workera: IMAP → parser → SQLite → resolver → documento del día.

Cada instalación sincroniza SOLO el Gmail y el RUT de su dueño (configurados en Ajustes).
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Callable, Iterable, Optional

from core.calculator import Day
from data.database import Database
from services.attendance_resolver import ResolucionDia, ResolverConfig, resolver_dia
from services.auth import Credenciales
from services.imap_client import WorkeraMailbox
from services.workera_parser import AlertaWorkera, WorkeraParseError, parse_email

DIAS_PRIMERA_SYNC = 45
# Sube cuando el lector aprende un tipo de correo nuevo: la próxima sincronización vuelve a leer los
# últimos DIAS_PRIMERA_SYNC días (correos que antes se ignoraron). 2 = «Solicitud de marcación aceptada».
VERSION_LECTOR = "2"
SOLAPE_DIAS = 3
CUENTA_PUENTE = "puente-google"
CARPETA_PUENTE = "gmail"


@dataclass
class ResultadoSync:
    correos_leidos: int = 0
    marcas_nuevas: int = 0
    alertas: int = 0
    ignorados_otro_rut: int = 0
    ignorados_remitente: int = 0
    pendientes_sin_rut: int = 0
    errores: list[str] = field(default_factory=list)
    fechas: set[str] = field(default_factory=set)
    ruts_encontrados: Counter = field(default_factory=Counter)

    def resumen(self) -> str:
        partes = [f"{self.marcas_nuevas} marca(s) nueva(s)", f"{self.alertas} alerta(s)"]
        if self.ignorados_otro_rut:
            partes.append(f"{self.ignorados_otro_rut} de otro RUT ignorada(s)")
        if self.pendientes_sin_rut:
            partes.append(f"{self.pendientes_sin_rut} esperando que configures tu RUT")
        if self.errores:
            partes.append(f"{len(self.errores)} error(es)")
        return ", ".join(partes)


def aplicar_resolucion_a_dia(day: Day, res: ResolucionDia) -> bool:
    """Lleva ingreso/salida resueltos al documento del día sin pisar lo editado a mano."""
    cambiado = False
    for campo in ("ingreso", "salida"):
        valor, fuente = getattr(res, campo), day.fuente.get(campo)
        if fuente == "manual":
            continue
        if valor is None:
            if fuente == "workera":          # la marca dejó de tener ese rol (inversión, descarte)
                setattr(day, campo, None)
                day.fuente.pop(campo, None)
                cambiado = True
            continue
        if getattr(day, campo) != valor or fuente != "workera":
            setattr(day, campo, valor)
            day.fuente[campo] = "workera"
            cambiado = True
    return cambiado


class SyncService:
    def __init__(self, db: Database, mailbox_factory: Callable[..., WorkeraMailbox] = WorkeraMailbox):
        self.db = db
        self._mailbox_factory = mailbox_factory

    def _releer_si_lector_nuevo(self) -> None:
        if self.db.get_meta("version_lector") != VERSION_LECTOR:
            self.olvidar_lo_leido()
            self.db.set_meta("version_lector", VERSION_LECTOR)

    def olvidar_lo_leido(self) -> None:
        """La próxima sincronización relee los últimos días (es idempotente: no duplica marcas)."""
        self.db.olvidar_uids()
        self.db.set_meta("ultima_sync_fecha", None)
        self.db.set_meta("ultima_sync_puente_fecha", None)

    @property
    def resolver_config(self) -> ResolverConfig:
        return ResolverConfig(**self.db.get_pref("resolver", {}))

    # ------------------------------------------------------------------ IMAP
    def sincronizar(self, cred: Credenciales, desde: Optional[date] = None,
                    hoy: Optional[date] = None) -> ResultadoSync:
        cred = cred.normalizada()
        if not cred.completas:
            raise ValueError("Configura tu Gmail y la contraseña de aplicación en Ajustes")
        hoy = hoy or date.today()
        self._releer_si_lector_nuevo()
        if desde is None:
            ultima = self.db.get_meta("ultima_sync_fecha")
            desde = (date.fromisoformat(ultima) - timedelta(days=SOLAPE_DIAS) if ultima
                     else hoy - timedelta(days=DIAS_PRIMERA_SYNC))
        caja = self._mailbox_factory(cred.imap())
        mensajes = caja.descargar(desde, self.db.uids_vistos(cred.usuario, cred.carpeta))
        res = self.procesar(mensajes, cred)
        if cred.rut:
            self.db.set_meta("ultima_sync", datetime.now().isoformat(timespec="seconds"))
            self.db.set_meta("ultima_sync_fecha", hoy.isoformat())
        return res

    def detectar_ruts(self, cred: Credenciales, dias: int = 30) -> Counter:
        """Lee correos recientes de Workera y cuenta los RUT encontrados (para el asistente inicial)."""
        cred = cred.normalizada()
        caja = self._mailbox_factory(cred.imap())
        sin_rut = Credenciales(**{**cred.__dict__, "rut": ""})
        return self.procesar(caja.descargar(date.today() - timedelta(days=dias)), sin_rut).ruts_encontrados

    # ------------------------------------------------------------------ Puente Google (Apps Script)
    async def sincronizar_puente(self, puente, rut: str, hoy: Optional[date] = None) -> ResultadoSync:
        """Igual que `sincronizar` pero los correos llegan del Puente Google en vez de IMAP."""
        hoy = hoy or date.today()
        self._releer_si_lector_nuevo()
        ultima = self.db.get_meta("ultima_sync_puente_fecha")
        desde = date.fromisoformat(ultima) - timedelta(days=SOLAPE_DIAS) if ultima else hoy - timedelta(days=DIAS_PRIMERA_SYNC)
        desde_epoch = int(datetime.combine(desde, datetime.min.time()).timestamp())
        cred = Credenciales(usuario=CUENTA_PUENTE, carpeta=CARPETA_PUENTE, rut=rut)
        vistos = self.db.uids_vistos(CUENTA_PUENTE, CARPETA_PUENTE)
        mensajes = [(uid, raw) for uid, raw in await puente.correos(desde_epoch) if uid not in vistos]
        res = self.procesar(mensajes, cred.normalizada() if rut else cred)
        if rut:
            self.db.set_meta("ultima_sync", datetime.now().isoformat(timespec="seconds"))
            self.db.set_meta("ultima_sync_puente_fecha", hoy.isoformat())
        return res

    async def detectar_ruts_puente(self, puente, dias: int = 30) -> Counter:
        cred = Credenciales(usuario=CUENTA_PUENTE, carpeta=CARPETA_PUENTE, rut="")
        return self.procesar(await puente.correos(dias=dias), cred).ruts_encontrados

    # ------------------------------------------------------------------ procesamiento
    def procesar(self, mensajes: Iterable[tuple[str, bytes]], cred: Credenciales) -> ResultadoSync:
        res = ResultadoSync()
        visto = lambda uid: self.db.marcar_uid_visto(cred.usuario, cred.carpeta, uid)  # noqa: E731
        for uid, raw in mensajes:
            res.correos_leidos += 1
            try:
                correo = parse_email(raw)
            except WorkeraParseError as exc:
                res.errores.append(f"Correo {uid}: {exc}")
                visto(uid)
                continue
            if correo is None:
                visto(uid)
                continue
            if not correo.remitente_valido:
                res.ignorados_remitente += 1
                visto(uid)
                continue
            datos = correo.datos
            rut = getattr(datos, "rut_trabajador", "") or getattr(datos, "run_trabajador", "")
            if rut:
                res.ruts_encontrados[rut] += 1
            if not cred.rut:
                res.pendientes_sin_rut += 1          # no se marca como visto: se importará luego
                continue
            if datos.pertenece_a(cred.rut) is False:
                res.ignorados_otro_rut += 1
                visto(uid)
                continue
            if isinstance(datos, AlertaWorkera):
                if self.db.guardar_alerta(datos, uid):
                    res.alertas += 1
                    res.fechas.add(datos.fecha)
            elif self.db.guardar_marcacion(datos, uid):
                res.marcas_nuevas += 1
                res.fechas.add(datos.fecha)
            visto(uid)
        for fecha in sorted(res.fechas):
            self.reconciliar(fecha)
        return res

    def reconciliar(self, fecha) -> Optional[ResolucionDia]:
        """Recalcula la resolución del día con todo lo guardado y actualiza el documento."""
        marcas, alerta = self.db.get_marcas(fecha), self.db.get_alerta(fecha)
        if not marcas and not alerta:
            return None
        fecha_iso = str(fecha) if not isinstance(fecha, date) else fecha.isoformat()
        res = resolver_dia(marcas, alerta, self.db.get_overrides(fecha), self.resolver_config, fecha=fecha_iso)
        self.db.actualizar_asignaciones(res)
        day = self.db.get_day(fecha)
        if aplicar_resolucion_a_dia(day, res):
            self.db.save_day(day)
        return res
