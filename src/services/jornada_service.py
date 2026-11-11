"""Casos de uso de la app (lo que hacen los botones). La UI solo llama a esto y pinta.

Une core.calculator (reglas), data.database (persistencia) y services.sync (Workera).
"""
from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import date, timedelta
from typing import Optional

from core import calculator as calc
from core.calculator import Config, Day, DayCalc, PeriodCalc, PlanOption, fmt_hms
from data.database import Database
from services.attendance_resolver import (
    ResolucionDia, overrides_invertir, overrides_mover_a_salida,
)
from services.sync import SyncService


@dataclass
class EstadoHoy:
    day: Day
    calc: DayCalc
    laboral: bool
    salida_estimada_s: Optional[int] = None
    hora_limite_s: Optional[int] = None
    aviso_salida_s: Optional[int] = None
    transcurrido_s: int = 0
    restante_s: int = 0
    progreso: float = 0.0
    saldo_semana_previo_s: int = 0
    saldo_semana_s: int = 0
    opciones: list[PlanOption] = field(default_factory=list)
    deuda: Optional[dict] = None
    cierre: Optional[dict] = None
    ultimo: Optional[dict] = None
    resolucion: Optional[ResolucionDia] = None


class JornadaService:
    def __init__(self, db: Database, sync: Optional[SyncService] = None):
        self.db = db
        self.sync = sync or SyncService(db)

    @property
    def cfg(self) -> Config:
        return self.db.get_config()

    def guardar_config(self, cfg: Config) -> None:
        self.db.save_config(cfg)

    # ------------------------------------------------------------------ lectura
    def dia(self, fecha) -> Day:
        return self.db.get_day(fecha)

    def _dias_semana(self, fecha) -> dict[date, Day]:
        return self.db.days_week(fecha)

    def _periodo_tope(self, fecha: date, cfg: Config):
        if cfg.tope_por != "periodo":
            return None
        return calc.rango_periodo(cfg.periodo_modo, fecha, cfg.ciclo_dia_inicio, cfg.periodo_desde, cfg.periodo_hasta)

    def _dias_para(self, fecha: date, cfg: Config) -> dict[date, Day]:
        periodo = self._periodo_tope(fecha, cfg)
        if periodo:
            return self.db.days_between(min(periodo[0], fecha - timedelta(days=7)), max(periodo[1], fecha + timedelta(days=7)))
        return self._dias_semana(fecha)

    def estado(self, fecha: date, ahora_s: int) -> EstadoHoy:
        cfg = self.cfg
        dias = self._dias_para(fecha, cfg)
        day = dias.get(fecha) or Day(fecha=fecha)
        periodo = self._periodo_tope(fecha, cfg)
        c = calc.calc_dia(day, cfg)
        st = EstadoHoy(day=day, calc=c, laboral=c.laboral, resolucion=self.resolucion(fecha))
        st.saldo_semana_previo_s = calc.saldo_previo_semana_s(fecha, dias, cfg)
        st.saldo_semana_s = calc.calc_semana(fecha, dias, cfg).saldo_s
        ing = calc.parse_hms(day.ingreso)
        if ing is None:
            return st
        st.opciones = calc.opciones_plan(day, dias, cfg, periodo)
        sal_real = calc.parse_hms(day.salida)
        if c.laboral:
            st.salida_estimada_s = calc.salida_plan_s(day, dias, cfg, periodo)
            limite = calc.hora_limite_s(day, dias, cfg, periodo)
            normal = calc.salida_normal_s(day, cfg)
            # Solo es relevante si se alcanza antes del máximo de HE del día (más allá no suman).
            if limite is not None and (cfg.max_he_s <= 0 or limite <= normal + cfg.max_he_s):
                st.hora_limite_s = limite
            st.deuda = calc.aviso_deuda(day, dias, cfg)
            st.cierre = calc.aviso_cierre_semana(day, dias, cfg, ahora_s)
            st.ultimo = calc.aviso_ultimo_dia(day, dias, cfg)
        if st.salida_estimada_s is not None:
            st.aviso_salida_s = calc.hora_aviso_salida_s(st.salida_estimada_s, cfg)
        fin = sal_real if sal_real is not None else ahora_s
        st.transcurrido_s = max(0, (fin - ing) % calc.DIA_S) if fin != ing else 0
        if st.salida_estimada_s is not None:
            total = max(1, st.salida_estimada_s - ing)
            st.restante_s = max(0, st.salida_estimada_s - fin)
            st.progreso = min(1.0, st.transcurrido_s / total)
        if sal_real is None:
            # saldo de la semana proyectado si sale ahora
            st.saldo_semana_s = st.saldo_semana_previo_s + calc.saldo_con_salida_s(day, ahora_s, cfg)
        return st

    def objetivo_aviso(self, fecha: date) -> Optional[int]:
        """Hora de salida a avisar por push (None si no corresponde: sin ingreso, ya salió, día libre)."""
        cfg = self.cfg
        day = self.dia(fecha)
        if not day.ingreso or day.salida or not calc.es_laboral(day, cfg):
            return None
        dias = self._dias_para(fecha, cfg)
        return calc.salida_plan_s(dias.get(fecha) or day, dias, cfg, self._periodo_tope(fecha, cfg))

    def resumen_semana(self, fecha: date, hoy: Optional[date] = None, ahora_s: Optional[int] = None):
        return calc.resumen_semana(fecha, self._dias_semana(fecha), self.cfg, hoy=hoy or date.today(),
                                   ahora_s=ahora_s)

    def periodo(self, ref: date, hoy: Optional[date] = None) -> PeriodCalc:
        cfg = self.cfg
        desde, hasta = calc.rango_periodo(cfg.periodo_modo, ref, cfg.ciclo_dia_inicio,
                                          cfg.periodo_desde, cfg.periodo_hasta)
        dias = self.db.days_between(desde - timedelta(days=7), hasta + timedelta(days=7))
        return calc.calc_periodo(dias, desde, hasta, cfg, hoy=hoy or date.today())

    def resolucion(self, fecha) -> Optional[ResolucionDia]:
        if not self.db.get_marcas(fecha) and not self.db.get_alerta(fecha):
            return None
        return self.sync.reconciliar(fecha)

    # ------------------------------------------------------------------ flujo diario
    def _guardar(self, day: Day) -> Day:
        self.db.save_day(day)
        return day

    def marcar_ingreso(self, fecha: date, hora_s: int) -> Day:
        day = self.dia(fecha)
        day.ingreso = fmt_hms(hora_s)
        day.fuente["ingreso"] = "app"
        return self._guardar(day)

    def elegir_plan(self, fecha: date, plan: str, antes_s: int = 0) -> Day:
        day = self.dia(fecha)
        day.plan, day.antes = plan, antes_s if plan == "adel" else 0
        return self._guardar(day)

    def marcar_salida(self, fecha: date, hora_s: int) -> DayCalc:
        day = self.dia(fecha)
        day.salida = fmt_hms(hora_s)
        day.fuente["salida"] = "app"
        self._guardar(day)
        return calc.calc_dia(day, self.cfg)

    def guardar_motivo(self, fecha: date, motivo: str) -> Day:
        day = self.dia(fecha)
        day.motivoHE = motivo.strip()
        return self._guardar(day)

    def guardar_dia_editado(self, nuevo: Day) -> Day:
        """Editor de días: lo que el usuario cambia a mano queda como fuente 'manual'."""
        previo = self.dia(nuevo.fecha)
        nuevo = replace(nuevo, fuente=dict(previo.fuente))
        for campo in ("ingreso", "salida"):
            if getattr(nuevo, campo) != getattr(previo, campo):
                if getattr(nuevo, campo):
                    nuevo.fuente[campo] = "manual"
                else:
                    nuevo.fuente.pop(campo, None)
        return self._guardar(nuevo)

    def responder_cierre(self, fecha: date, respuesta: str) -> Day:
        day = self.dia(fecha)
        day.avisoCierre = respuesta
        return self._guardar(day)

    # ------------------------------------------------------------------ días no laborales
    def cambio_de_dia(self, fecha_trabajada: date, fecha_libre: date) -> tuple[Day, Day]:
        trabajado, libre = calc.aplicar_cambio_dia(self.dia(fecha_trabajada), self.dia(fecha_libre))
        self._guardar(trabajado)
        self._guardar(libre)
        return trabajado, libre

    def deshacer_cambio(self, fecha_trabajada: date) -> None:
        trabajado = self.dia(fecha_trabajada)
        if not trabajado.cambioDe:
            return
        t, l = calc.deshacer_cambio_dia(trabajado, self.dia(trabajado.cambioDe))
        self._guardar(t)
        self._guardar(l)

    def candidatos_cambio(self, fecha: date) -> list[date]:
        """Días laborales de la misma semana sin registro, para elegir cuál se recupera."""
        cfg = self.cfg
        dias = self._dias_semana(fecha)
        return [f for f in calc.dias_de_semana(fecha)
                if f != fecha and calc.es_laboral(dias.get(f) or Day(fecha=f), cfg)
                and calc.calc_dia(dias.get(f) or Day(fecha=f), cfg).estado == "sin_registro"]

    # ------------------------------------------------------------------ acciones Workera
    def _liberar_fuentes(self, fecha) -> None:
        day = self.dia(fecha)
        for campo in ("ingreso", "salida"):
            if day.fuente.get(campo) in ("manual", "app", "alerta"):
                day.fuente[campo] = "workera"
        self._guardar(day)

    def invertir(self, fecha) -> Optional[ResolucionDia]:
        """⇄ Invertir Entrada/Salida."""
        res = self.resolucion(fecha)
        if res and (res.ingreso_checksum or res.salida_checksum):
            self.db.set_overrides(fecha, overrides_invertir(res, self.db.get_overrides(fecha)))
            self._liberar_fuentes(fecha)
            return self.sync.reconciliar(fecha)
        day = self.dia(fecha)
        day.ingreso, day.salida = day.salida, day.ingreso
        day.fuente = {k: "manual" for k in ("ingreso", "salida") if getattr(day, k)}
        self._guardar(day)
        return None

    def mover_a_salida(self, fecha, checksum: str) -> Optional[ResolucionDia]:
        self.db.set_overrides(fecha, overrides_mover_a_salida(checksum, self.db.get_overrides(fecha)))
        return self.sync.reconciliar(fecha)

    def marcar_como_ingreso(self, fecha, checksum: str) -> Optional[ResolucionDia]:
        """Respuesta 'Es turno de tarde' del banner: la marca es un ingreso."""
        overrides = dict(self.db.get_overrides(fecha))
        overrides[checksum] = "ingreso"
        self.db.set_overrides(fecha, overrides)
        return self.sync.reconciliar(fecha)

    def deshacer_ajustes_workera(self, fecha) -> Optional[ResolucionDia]:
        self.db.set_overrides(fecha, {})
        self._liberar_fuentes(fecha)
        return self.sync.reconciliar(fecha)

    def aplicar_sugerencia(self, fecha, campo: str) -> Day:
        res = self.resolucion(fecha)
        sug = res.sugerencia(campo) if res else None
        day = self.dia(fecha)
        if sug and not getattr(day, campo):
            setattr(day, campo, sug.hora)
            day.fuente[campo] = "alerta"
            self._guardar(day)
        return day

    # ------------------------------------------------------------------ vacaciones / licencias
    TIPOS_AUSENCIA = ("vacaciones", "licencia", "permiso", "feriado")
    MAX_DIAS_RANGO = 92

    def marcar_rango(self, desde: date, hasta: date, tipo: Optional[str]) -> dict:
        """Marca de una vez los días laborales de un rango (también futuros).

        `tipo` ∈ TIPOS_AUSENCIA, o None para quitar la marca (vuelven a ser laborales).
        No toca fines de semana ni días libres por defecto, días con marcas de ingreso/salida
        (se informan como omitidos) ni días de cambio de día."""
        if tipo is not None and tipo not in self.TIPOS_AUSENCIA:
            raise ValueError(f"Tipo inválido: {tipo!r}")
        if hasta < desde:
            raise ValueError("La fecha de término es anterior a la de inicio")
        if (hasta - desde).days + 1 > self.MAX_DIAS_RANGO:
            raise ValueError(f"El rango no puede superar {self.MAX_DIAS_RANGO} días")
        cfg = self.cfg
        dias = self.db.days_between(desde, hasta)
        marcados: list[date] = []
        con_marcas: list[date] = []
        f = desde
        while f <= hasta:
            day = dias.get(f) or Day(fecha=f)
            laborable = f.weekday() in cfg.dias_laborales
            if tipo is None:
                if day.tipo in self.TIPOS_AUSENCIA:
                    day.tipo = None
                    self._guardar(day)
                    marcados.append(f)
            elif laborable and not day.cambioDe and day.tipo != "cambio":
                if day.ingreso or day.salida:
                    con_marcas.append(f)
                elif day.tipo != tipo:
                    day.tipo = tipo
                    self._guardar(day)
                    marcados.append(f)
            f += timedelta(days=1)
        return {"marcados": marcados, "con_marcas": con_marcas}

    # ------------------------------------------------------------------ periodo
    def borrar_periodo(self, desde: date, hasta: date) -> int:
        return self.db.borrar_periodo(desde, hasta)
