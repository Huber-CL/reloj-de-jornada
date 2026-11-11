"""Motor de cálculo de Reloj de Jornada (reglas de reloj-de-jornada.md).

Código puro: sin I/O, sin UI y sin leer el reloj del sistema (la hora actual se recibe por
parámetro). Las horas se manejan como segundos desde medianoche y las duraciones en segundos.
"""
from __future__ import annotations

import calendar
from dataclasses import asdict, dataclass, field, fields, replace
from datetime import date, timedelta
from typing import Mapping, Optional

H = 3600
DIA_S = 86400

TIPOS_DIA = ("laboral", "libre", "feriado", "vacaciones", "licencia", "permiso", "cambio")
PLANES = ("normal", "comp", "adel", "he1", "he2", "tope")
OPCIONES_ADELANTO_S = (1800, 3600, 5400, 7200)
HORA_AVISO_CIERRE_S = 14 * H

Dias = Mapping[date, "Day"]


# ----------------------------------------------------------------------------- tiempo
def parse_hms(valor) -> Optional[int]:
    """'hh:mm' o 'hh:mm:ss' → segundos desde medianoche. None/'' → None."""
    if valor is None:
        return None
    if isinstance(valor, int):
        return valor
    texto = str(valor).strip()
    if not texto:
        return None
    partes = texto.split(":")
    if len(partes) not in (2, 3) or not all(p.isdigit() for p in partes):
        raise ValueError(f"Hora inválida: {valor!r}")
    h, m = int(partes[0]), int(partes[1])
    s = int(partes[2]) if len(partes) == 3 else 0
    if not (0 <= h < 24 and 0 <= m < 60 and 0 <= s < 60):
        raise ValueError(f"Hora fuera de rango: {valor!r}")
    return h * H + m * 60 + s


def fmt_hms(segundos: int, con_segundos: bool = True) -> str:
    """Segundos desde medianoche → 'hh:mm:ss' (módulo 24 h)."""
    seg = int(segundos) % DIA_S
    h, resto = divmod(seg, H)
    m, s = divmod(resto, 60)
    return f"{h:02d}:{m:02d}:{s:02d}" if con_segundos else f"{h:02d}:{m:02d}"


def fmt_duracion(segundos: int, con_segundos: bool = False) -> str:
    """Duración con signo → 'h:mm' o 'h:mm:ss' (ej. -1:30)."""
    signo = "-" if segundos < 0 else ""
    h, resto = divmod(abs(int(segundos)), H)
    m, s = divmod(resto, 60)
    return f"{signo}{h}:{m:02d}:{s:02d}" if con_segundos else f"{signo}{h}:{m:02d}"


def to_date(valor) -> date:
    return valor if isinstance(valor, date) else date.fromisoformat(str(valor))


def lunes_de(fecha: date) -> date:
    return fecha - timedelta(days=fecha.weekday())


def dias_de_semana(fecha: date) -> list[date]:
    lunes = lunes_de(fecha)
    return [lunes + timedelta(days=i) for i in range(7)]


# ----------------------------------------------------------------------------- modelos
@dataclass
class Config:
    jornada_h: float = 8.0
    colacion_min: int = 60
    max_devolver_dia_h: float = 2.0
    max_he_dia_h: float = 2.0
    tope_saldo_h: float = 10.0          # 0 = sin tope
    tope_por: str = "semana"            # "semana" | "periodo"
    sueldo_base: float = 0.0
    jornada_semanal_h: float = 42.0     # Ley 40 Horas (desde abril 2026)
    valor_he_manual: Optional[float] = None
    valor_hora_extraordinaria: Optional[float] = None
    pagar_saldo_neto: bool = True
    mostrar_segundos: bool = True
    aviso_salida_min: int = 5
    aviso_sonido: bool = True
    dias_laborales: tuple[int, ...] = (0, 1, 2, 3, 4)   # lunes=0
    periodo_modo: str = "semana"        # "semana" | "mes" | "ciclo" | "fechas"
    ciclo_dia_inicio: int = 25
    periodo_desde: Optional[str] = None
    periodo_hasta: Optional[str] = None
    # Vacaciones (feriado legal, en días hábiles): saldo que informa RR.HH. a una fecha de corte;
    # las vacaciones marcadas desde esa fecha (inclusive) se descuentan.
    vac_saldo_dias: Optional[float] = None
    vac_saldo_fecha: Optional[str] = None
    vac_acumular: bool = False          # sumar lo que se va ganando después del corte
    vac_dias_anuales: float = 15.0      # 15 días hábiles al año (art. 67 Código del Trabajo) + progresivos

    @property
    def jornada_s(self) -> int:
        return round(self.jornada_h * H)

    @property
    def colacion_s(self) -> int:
        return int(self.colacion_min) * 60

    @property
    def max_devolver_s(self) -> int:
        return round(self.max_devolver_dia_h * H)

    @property
    def max_he_s(self) -> int:
        return round(self.max_he_dia_h * H)

    @property
    def tope_s(self) -> int:
        return round(self.tope_saldo_h * H)

    @classmethod
    def from_dict(cls, datos: Optional[Mapping]) -> "Config":
        nombres = {f.name for f in fields(cls)}
        limpio = {k: v for k, v in (datos or {}).items() if k in nombres}
        if "dias_laborales" in limpio:
            limpio["dias_laborales"] = tuple(limpio["dias_laborales"])
        return cls(**limpio)

    def to_dict(self) -> dict:
        d = asdict(self)
        d["dias_laborales"] = list(self.dias_laborales)
        return d


@dataclass
class Day:
    """Documento de un día (days/<AAAA-MM-DD>)."""

    fecha: date
    ingreso: Optional[str] = None
    salida: Optional[str] = None
    tipo: Optional[str] = None          # None = según día de la semana
    plan: Optional[str] = None
    antes: int = 0                      # segundos que sale antes (plan "adel")
    objetivoH: Optional[float] = None
    colacionMin: Optional[int] = None
    extras: list = field(default_factory=list)   # [{inicio, fin, ref}]
    motivoHE: str = ""
    nota: str = ""
    cambioDe: Optional[str] = None      # en el día TRABAJADO: fecha del día libre que reemplaza
    cambioCon: Optional[str] = None     # en el día LIBRE (tipo "cambio"): fecha trabajada
    avisoCierre: Optional[str] = None   # si | no | ok
    # Origen de ingreso/salida: "app" (botón Ahora), "manual" (editor), "workera", "alerta".
    # La sincronización Workera nunca sobrescribe un valor "manual".
    fuente: dict = field(default_factory=dict)

    def __post_init__(self):
        self.fecha = to_date(self.fecha)
        if self.tipo is not None and self.tipo not in TIPOS_DIA:
            raise ValueError(f"Tipo de día inválido: {self.tipo!r}")
        if self.plan is not None and self.plan not in PLANES:
            raise ValueError(f"Plan inválido: {self.plan!r}")

    @classmethod
    def from_dict(cls, datos: Mapping, fecha=None) -> "Day":
        nombres = {f.name for f in fields(cls)}
        limpio = {k: v for k, v in datos.items() if k in nombres}
        if fecha is not None:
            limpio["fecha"] = fecha
        return cls(**limpio)

    def to_dict(self) -> dict:
        d = asdict(self)
        d["fecha"] = self.fecha.isoformat()
        return d


def _dia(dias: Dias, fecha: date) -> Day:
    return dias.get(fecha) or Day(fecha=fecha)


# ----------------------------------------------------------------------------- día
def tipo_efectivo(day: Day, cfg: Config) -> str:
    if day.cambioDe:
        return "laboral"            # día trabajado en cambio de otro: cuenta como jornada normal
    if day.tipo:
        return day.tipo
    return "laboral" if day.fecha.weekday() in cfg.dias_laborales else "libre"


def es_laboral(day: Day, cfg: Config) -> bool:
    return tipo_efectivo(day, cfg) == "laboral"


def meta_dia_s(day: Day, cfg: Config) -> int:
    if not es_laboral(day, cfg):
        return 0
    return round(day.objetivoH * H) if day.objetivoH is not None else cfg.jornada_s


def colacion_dia_s(day: Day, cfg: Config) -> int:
    if not es_laboral(day, cfg):
        return 0                    # días no laborales: sin descontar colación
    return int(day.colacionMin) * 60 if day.colacionMin is not None else cfg.colacion_s


def duracion_extras_s(extras) -> int:
    total = 0
    for bloque in extras or []:
        ini, fin = parse_hms(bloque.get("inicio")), parse_hms(bloque.get("fin"))
        if ini is not None and fin is not None:
            total += (fin - ini) % DIA_S
    return total


def salida_normal_s(day: Day, cfg: Config) -> Optional[int]:
    ing = parse_hms(day.ingreso)
    if ing is None:
        return None
    return ing + meta_dia_s(day, cfg) + colacion_dia_s(day, cfg)


@dataclass
class DayCalc:
    fecha: date
    tipo: str
    laboral: bool
    estado: str                 # completo | en_curso | incompleto | sin_registro
    meta_s: int
    colacion_s: int
    trabajadas_s: int = 0
    he_bruta_s: int = 0         # sin aplicar el máx. HE diario
    he_s: int = 0
    faltante_s: int = 0
    saldo_s: int = 0
    extras_s: int = 0
    salida_normal_s: Optional[int] = None

    @property
    def he_excedente_s(self) -> int:
        return self.he_bruta_s - self.he_s


def calc_dia(day: Day, cfg: Config) -> DayCalc:
    tipo = tipo_efectivo(day, cfg)
    laboral = tipo == "laboral"
    meta, col = meta_dia_s(day, cfg), colacion_dia_s(day, cfg)
    ing, sal = parse_hms(day.ingreso), parse_hms(day.salida)
    calc = DayCalc(
        fecha=day.fecha, tipo=tipo, laboral=laboral, estado="sin_registro", meta_s=meta,
        colacion_s=col, extras_s=duracion_extras_s(day.extras),
        salida_normal_s=(ing + meta + col) if ing is not None else None,
    )
    if ing is None and sal is None:
        return calc
    if sal is None:
        calc.estado = "en_curso"
        return calc
    if ing is None:
        calc.estado = "incompleto"
        return calc
    calc.estado = "completo"
    tramo = (sal - ing) % DIA_S
    calc.trabajadas_s = max(0, tramo - col)
    calc.he_bruta_s = max(0, calc.trabajadas_s - meta)
    calc.he_s = min(calc.he_bruta_s, cfg.max_he_s) if laboral and cfg.max_he_s > 0 else calc.he_bruta_s
    calc.faltante_s = max(0, meta - calc.trabajadas_s) if laboral else 0
    calc.saldo_s = calc.he_s - calc.faltante_s
    return calc


def saldo_con_salida_s(day: Day, salida_s: int, cfg: Config) -> int:
    """Saldo que tendría el día si se sale a `salida_s`."""
    return calc_dia(replace(day, salida=fmt_hms(salida_s)), cfg).saldo_s


# ----------------------------------------------------------------------------- semana
@dataclass
class WeekCalc:
    lunes: date
    domingo: date
    trabajadas_s: int
    he_s: int
    faltante_s: int
    saldo_s: int
    saldo_computable_s: int
    extras_s: int
    dias: list[DayCalc]

    @property
    def excede_tope(self) -> bool:
        return self.saldo_s != self.saldo_computable_s

    @property
    def exceso_s(self) -> int:
        return self.saldo_s - self.saldo_computable_s


def calc_semana(fecha: date, dias: Dias, cfg: Config, desde: Optional[date] = None,
                hasta: Optional[date] = None, excluir: Optional[date] = None) -> WeekCalc:
    fechas = [f for f in dias_de_semana(fecha)
              if (desde is None or f >= desde) and (hasta is None or f <= hasta) and f != excluir]
    calcs = [calc_dia(_dia(dias, f), cfg) for f in fechas]
    saldo = sum(c.saldo_s for c in calcs)
    computable = min(saldo, cfg.tope_s) if cfg.tope_por == "semana" and cfg.tope_s > 0 else saldo
    lunes = lunes_de(fecha)
    return WeekCalc(
        lunes=lunes, domingo=lunes + timedelta(days=6),
        trabajadas_s=sum(c.trabajadas_s for c in calcs), he_s=sum(c.he_s for c in calcs),
        faltante_s=sum(c.faltante_s for c in calcs), saldo_s=saldo, saldo_computable_s=computable,
        extras_s=sum(c.extras_s for c in calcs), dias=calcs,
    )


def saldo_previo_semana_s(fecha: date, dias: Dias, cfg: Config) -> int:
    """Saldo del resto de la semana (lun–dom), excluyendo `fecha`."""
    return calc_semana(fecha, dias, cfg, excluir=fecha).saldo_s


def saldo_previo_tope_s(fecha: date, dias: Dias, cfg: Config,
                        periodo: Optional[tuple[date, date]] = None) -> int:
    """Saldo acumulado relevante para el tope (semana o periodo), excluyendo `fecha`."""
    if cfg.tope_por == "periodo" and periodo:
        desde, hasta = periodo
        total, f = 0, desde
        while f <= hasta:
            if f != fecha:
                total += calc_dia(_dia(dias, f), cfg).saldo_s
            f += timedelta(days=1)
        return total
    return saldo_previo_semana_s(fecha, dias, cfg)


# ----------------------------------------------------------------------------- planes
@dataclass
class PlanOption:
    codigo: str
    etiqueta: str
    salida_s: int
    delta_s: int                # respecto a la salida normal (+ = HE, − = sale antes)
    habilitada: bool = True
    recomendada: bool = False
    antes_s: int = 0
    nota: str = ""


def _disponible_tope_s(fecha: date, dias: Dias, cfg: Config, periodo) -> Optional[int]:
    if cfg.tope_s <= 0:
        return None
    return cfg.tope_s - saldo_previo_tope_s(fecha, dias, cfg, periodo)


def opciones_plan(day: Day, dias: Dias, cfg: Config,
                  periodo: Optional[tuple[date, date]] = None) -> list[PlanOption]:
    """Opciones de "¿Cómo será tu jornada hoy?" con su hora de salida."""
    normal = salida_normal_s(day, cfg)
    if normal is None or not es_laboral(day, cfg):
        return []
    saldo_sem = saldo_previo_semana_s(day.fecha, dias, cfg)
    disponible = _disponible_tope_s(day.fecha, dias, cfg, periodo)

    def permitido(delta: int) -> bool:
        if delta <= 0:
            return True
        if cfg.max_he_s > 0 and delta > cfg.max_he_s:
            return False
        return disponible is None or delta <= disponible

    opciones = [PlanOption("normal", "Jornada normal", normal, 0)]

    if saldo_sem > 0:
        delta = -min(saldo_sem, cfg.max_devolver_s)
        nota = f"Usa {fmt_duracion(-delta)} a favor"
    else:
        delta = min(-saldo_sem, cfg.max_devolver_s)
        nota = f"Devuelve {fmt_duracion(delta)} de deuda" if delta else "Semana ya en saldo cero"
    opciones.append(PlanOption("comp", "Compensar", normal + delta, delta, permitido(delta),
                               recomendada=saldo_sem < 0, nota=nota))

    a_favor = max(saldo_sem, 0)
    for antes in OPCIONES_ADELANTO_S:
        usa = min(antes, a_favor)
        deuda = antes - usa
        nota = f"Usa {fmt_duracion(usa)} a favor" + (f", queda deuda {fmt_duracion(deuda)}" if deuda else "")
        opciones.append(PlanOption("adel", f"Salir {fmt_duracion(antes)} antes", normal - antes,
                                   -antes, antes_s=antes, nota=nota))

    for codigo, horas in (("he1", 1), ("he2", 2)):
        opciones.append(PlanOption(codigo, f"+{horas} HE", normal + horas * H, horas * H,
                                   permitido(horas * H)))

    if disponible is not None:
        hasta_tope = min(disponible, cfg.max_he_s) if cfg.max_he_s > 0 else disponible
        if hasta_tope > 0 and hasta_tope % H != 0:
            opciones.append(PlanOption("tope", "Hasta el tope", normal + hasta_tope, hasta_tope,
                                       nota=f"+{fmt_duracion(hasta_tope)} HE"))
    return opciones


def salida_plan_s(day: Day, dias: Dias, cfg: Config,
                  periodo: Optional[tuple[date, date]] = None) -> Optional[int]:
    """Hora de salida estimada según el plan guardado en el día."""
    normal = salida_normal_s(day, cfg)
    if normal is None:
        return None
    if not es_laboral(day, cfg):
        return None
    plan = day.plan or "normal"
    if plan == "adel":
        return normal - int(day.antes or 0)
    for op in opciones_plan(day, dias, cfg, periodo):
        if op.codigo == plan:
            return op.salida_s
    return normal


def hora_limite_s(day: Day, dias: Dias, cfg: Config,
                  periodo: Optional[tuple[date, date]] = None) -> Optional[int]:
    """Hora a partir de la cual se supera el tope de saldo."""
    normal = salida_normal_s(day, cfg)
    disponible = _disponible_tope_s(day.fecha, dias, cfg, periodo)
    if normal is None or disponible is None or not es_laboral(day, cfg):
        return None
    return normal + disponible


def hora_aviso_salida_s(salida_s: int, cfg: Config) -> int:
    return salida_s - cfg.aviso_salida_min * 60


# ----------------------------------------------------------------------------- avisos
def dias_laborales_semana(fecha: date, dias: Dias, cfg: Config) -> list[date]:
    return [f for f in dias_de_semana(fecha) if es_laboral(_dia(dias, f), cfg)]


def es_penultimo_laboral(fecha: date, dias: Dias, cfg: Config) -> bool:
    lab = dias_laborales_semana(fecha, dias, cfg)
    return len(lab) >= 2 and lab[-2] == fecha


def es_ultimo_laboral(fecha: date, dias: Dias, cfg: Config) -> bool:
    lab = dias_laborales_semana(fecha, dias, cfg)
    return bool(lab) and lab[-1] == fecha


def aviso_deuda(day: Day, dias: Dias, cfg: Config) -> Optional[dict]:
    """Deuda pendiente de la semana y lo sugerido para hoy."""
    saldo = saldo_previo_semana_s(day.fecha, dias, cfg)
    if saldo >= 0 or not es_laboral(day, cfg):
        return None
    deuda = -saldo
    return {"deuda_s": deuda, "sugerido_hoy_s": min(deuda, cfg.max_devolver_s), "plan_recomendado": "comp"}


def aviso_cierre_semana(day: Day, dias: Dias, cfg: Config, ahora_s: int) -> Optional[dict]:
    """Penúltimo día laboral desde las 14:00: saldo proyectado y propuesta de compensar mañana."""
    if day.avisoCierre or ahora_s < HORA_AVISO_CIERRE_S or not es_penultimo_laboral(day.fecha, dias, cfg):
        return None
    salida = parse_hms(day.salida)
    if salida is None:
        salida = salida_plan_s(day, dias, cfg)
    hoy = saldo_con_salida_s(day, salida, cfg) if salida is not None else 0
    proyectado = saldo_previo_semana_s(day.fecha, dias, cfg) + hoy
    manana = dias_laborales_semana(day.fecha, dias, cfg)[-1]
    compensar = (min(proyectado, cfg.max_devolver_s) if proyectado > 0
                 else -min(-proyectado, cfg.max_devolver_s))
    return {"saldo_proyectado_s": proyectado, "manana": manana, "compensar_manana_s": compensar}


def aviso_ultimo_dia(day: Day, dias: Dias, cfg: Config) -> Optional[dict]:
    """Último día laboral: hora para cerrar la semana en saldo cero."""
    normal = salida_normal_s(day, cfg)
    if normal is None or not es_ultimo_laboral(day.fecha, dias, cfg):
        return None
    saldo = saldo_previo_semana_s(day.fecha, dias, cfg)
    ajuste = max(-cfg.max_devolver_s, min(cfg.max_devolver_s, -saldo))
    return {"salida_s": normal + ajuste, "saldo_previo_s": saldo,
            "cierra_en_cero": abs(saldo) <= cfg.max_devolver_s}


# ----------------------------------------------------------------------------- cambio de día
def aplicar_cambio_dia(trabajado: Day, libre: Day) -> tuple[Day, Day]:
    """`trabajado` (ej. sábado) cuenta como jornada normal; `libre` (ej. viernes) queda libre."""
    if lunes_de(trabajado.fecha) != lunes_de(libre.fecha):
        raise ValueError("El cambio de día debe ser dentro de la misma semana (lun–dom)")
    if trabajado.fecha == libre.fecha:
        raise ValueError("El día trabajado y el día libre deben ser distintos")
    return (replace(trabajado, cambioDe=libre.fecha.isoformat()),
            replace(libre, tipo="cambio", cambioCon=trabajado.fecha.isoformat()))


def deshacer_cambio_dia(trabajado: Day, libre: Day) -> tuple[Day, Day]:
    return replace(trabajado, cambioDe=None), replace(libre, tipo=None, cambioCon=None)


# ----------------------------------------------------------------------------- periodo y valor HE
def valor_hora_extra(cfg: Config) -> float:
    """Código del Trabajo: sueldo ÷ 30 × 28 ÷ (jornada semanal × 4) × 1,5."""
    if cfg.valor_he_manual is not None:
        return float(cfg.valor_he_manual)
    if cfg.sueldo_base <= 0 or cfg.jornada_semanal_h <= 0:
        return 0.0
    return cfg.sueldo_base / 30 * 28 / (cfg.jornada_semanal_h * 4) * 1.5


def _fecha_ajustada(anio: int, mes: int, dia: int) -> date:
    return date(anio, mes, min(dia, calendar.monthrange(anio, mes)[1]))


def _mover_mes(anio: int, mes: int, k: int) -> tuple[int, int]:
    idx = anio * 12 + (mes - 1) + k
    return idx // 12, idx % 12 + 1


def rango_periodo(modo: str, ref: date, ciclo_dia_inicio: int = 25,
                  desde=None, hasta=None) -> tuple[date, date]:
    if modo == "semana":
        lunes = lunes_de(ref)
        return lunes, lunes + timedelta(days=6)
    if modo == "mes":
        return date(ref.year, ref.month, 1), _fecha_ajustada(ref.year, ref.month, 31)
    if modo == "ciclo":
        inicio_mes = _fecha_ajustada(ref.year, ref.month, ciclo_dia_inicio)
        if ref >= inicio_mes:
            sig = _mover_mes(ref.year, ref.month, 1)
            return inicio_mes, _fecha_ajustada(*sig, ciclo_dia_inicio) - timedelta(days=1)
        ant = _mover_mes(ref.year, ref.month, -1)
        return _fecha_ajustada(*ant, ciclo_dia_inicio), inicio_mes - timedelta(days=1)
    if modo == "fechas":
        if desde is None or hasta is None:
            raise ValueError("El modo 'fechas' requiere desde y hasta")
        d, h = to_date(desde), to_date(hasta)
        if h < d:
            raise ValueError("'hasta' no puede ser anterior a 'desde'")
        return d, h
    raise ValueError(f"Modo de periodo inválido: {modo!r}")


@dataclass
class ResumenSemana:
    """Cómo voy en la semana (lun–dom): meta, cuánto llevo, cuánto falta y cuánto toca por día."""
    lunes: date
    domingo: date
    meta_s: int                 # suma de la meta de los días laborales (feriados/permisos/cambios: 0)
    llevas_s: int               # trabajadas, incluido el día en curso hasta `ahora_s`
    faltan_s: int               # max(0, meta − llevas): horas para completar la semana
    exceso_s: int               # max(0, llevas − meta): horas por sobre la meta semanal
    he_s: int                   # horas extra de la semana (con tope diario)
    faltante_s: int
    saldo_s: int                # he − faltantes (días completos), como en la tabla semanal
    dias_laborales: int
    dias_restantes: int         # laborales desde hoy (hoy cuenta si aún no marcas salida)
    por_dia_s: Optional[int]    # faltan / días restantes
    sin_registro: list[date]    # laborales pasados sin marcas (cuentan en la meta)
    salida_hoy_s: Optional[int] = None   # si hoy está en curso: hora en que completarías la semana


def resumen_semana(fecha: date, dias: Dias, cfg: Config, hoy: Optional[date] = None,
                   ahora_s: Optional[int] = None) -> ResumenSemana:
    hoy = hoy or fecha
    semana = calc_semana(fecha, dias, cfg)
    lunes, domingo = semana.lunes, semana.domingo
    meta = llevas = 0
    laborales = restantes = 0
    sin_registro: list[date] = []
    salida_hoy = None
    for c in semana.dias:
        day = _dia(dias, c.fecha)
        if c.laboral:
            laborales += 1
            meta += c.meta_s
        llevas += c.trabajadas_s
        en_curso = c.estado == "en_curso" and c.fecha == hoy and ahora_s is not None
        if en_curso:
            llevas += calc_dia(replace(day, salida=fmt_hms(ahora_s)), cfg).trabajadas_s
        if c.laboral and (c.fecha > hoy or (c.fecha == hoy and c.estado != "completo")):
            restantes += 1
        if c.laboral and c.fecha < hoy and c.estado == "sin_registro":
            sin_registro.append(c.fecha)
    faltan = max(0, meta - llevas)
    hoy_calc = next((c for c in semana.dias if c.fecha == hoy), None)
    if hoy_calc and hoy_calc.estado == "en_curso" and ahora_s is not None:
        # Si hoy fuera el último día: a qué hora completas la meta semanal (colación incluida si aún no pasa).
        ing = parse_hms(_dia(dias, hoy).ingreso)
        trab_hoy = calc_dia(replace(_dia(dias, hoy), salida=fmt_hms(ahora_s)), cfg).trabajadas_s
        resto = faltan + trab_hoy
        salida_hoy = ing + resto + (hoy_calc.colacion_s if resto > 0 else 0)
    return ResumenSemana(
        lunes=lunes, domingo=domingo, meta_s=meta, llevas_s=llevas, faltan_s=faltan,
        exceso_s=max(0, llevas - meta), he_s=semana.he_s, faltante_s=semana.faltante_s,
        saldo_s=semana.saldo_s, dias_laborales=laborales, dias_restantes=restantes,
        por_dia_s=(faltan // restantes) if restantes else None, sin_registro=sin_registro,
        salida_hoy_s=salida_hoy,
    )


@dataclass
class SemanaFila:
    lunes: date
    domingo: date
    he_s: int
    faltante_s: int
    saldo_s: int
    saldo_computable_s: int


@dataclass
class PeriodCalc:
    desde: date
    hasta: date
    trabajadas_s: int
    he_s: int
    faltante_s: int
    saldo_neto_s: int
    extras_s: int
    dias_trabajados: int
    semanas: list[SemanaFila]
    dias: list[DayCalc]
    sin_registro: list[date]
    valor_he: float
    monto_he: int
    monto_extras: int

    @property
    def monto_total(self) -> int:
        return self.monto_he + self.monto_extras


def calc_periodo(dias: Dias, desde: date, hasta: date, cfg: Config,
                 hoy: Optional[date] = None) -> PeriodCalc:
    semanas: list[SemanaFila] = []
    calcs: list[DayCalc] = []
    lunes = lunes_de(desde)
    while lunes <= hasta:
        w = calc_semana(lunes, dias, cfg, desde=desde, hasta=hasta)
        semanas.append(SemanaFila(max(lunes, desde), min(w.domingo, hasta), w.he_s,
                                  w.faltante_s, w.saldo_s, w.saldo_computable_s))
        calcs.extend(w.dias)
        lunes += timedelta(days=7)

    saldo_bruto = sum(s.saldo_s for s in semanas)
    if cfg.tope_por == "periodo" and cfg.tope_s > 0:
        saldo_neto = min(saldo_bruto, cfg.tope_s)
    else:
        saldo_neto = sum(s.saldo_computable_s for s in semanas)

    he_total = sum(c.he_s for c in calcs)
    extras_total = sum(c.extras_s for c in calcs)
    valor = valor_hora_extra(cfg)
    base_s = saldo_neto if cfg.pagar_saldo_neto else he_total
    monto_he = round(max(0, base_s) / H * valor)
    monto_ext = round(extras_total / H * cfg.valor_hora_extraordinaria) if cfg.valor_hora_extraordinaria else 0

    limite = min(hasta, hoy) if hoy else hasta
    sin_registro = [c.fecha for c in calcs
                    if c.laboral and c.estado == "sin_registro" and c.fecha <= limite]
    return PeriodCalc(
        desde=desde, hasta=hasta, trabajadas_s=sum(c.trabajadas_s for c in calcs), he_s=he_total,
        faltante_s=sum(c.faltante_s for c in calcs), saldo_neto_s=saldo_neto, extras_s=extras_total,
        dias_trabajados=sum(1 for c in calcs if c.trabajadas_s > 0), semanas=semanas, dias=calcs,
        sin_registro=sin_registro, valor_he=valor, monto_he=monto_he, monto_extras=monto_ext,
    )


# ----------------------------------------------------------------------------- vacaciones
@dataclass
class TramoVacaciones:
    desde: date
    hasta: date
    dias: int                   # días hábiles descontados
    futuro: bool                # programado (empieza después de hoy)


@dataclass
class SaldoVacaciones:
    configurado: bool
    corte: Optional[date]
    saldo_inicial: float        # lo que informó RR.HH. a la fecha de corte
    acumulado: float            # ganado después del corte (si vac_acumular)
    tomados: int                # días de vacaciones desde el corte hasta hoy (inclusive)
    programados: int            # días de vacaciones marcados después de hoy
    disponibles: float          # saldo_inicial + acumulado − tomados − programados
    tramos: list                # [TramoVacaciones], más recientes primero


def meses_completos(desde: date, hasta: date) -> int:
    if hasta <= desde:
        return 0
    n = (hasta.year - desde.year) * 12 + hasta.month - desde.month
    if hasta.day < desde.day:
        n -= 1
    return max(0, n)


def tramos_vacaciones(fechas: list, dias: Mapping, cfg: Config, hoy: date) -> list:
    """Agrupa días de vacaciones en tramos: dos días quedan en el mismo tramo si entre ellos solo
    hay días no laborales (fin de semana) o feriados."""
    tramos: list[TramoVacaciones] = []
    for f in sorted(fechas):
        if tramos:
            t = tramos[-1]
            hueco = [t.hasta + timedelta(days=i) for i in range(1, (f - t.hasta).days)]
            if len(hueco) <= 6 and all(tipo_efectivo(_dia(dias, d), cfg) in ("libre", "feriado", "cambio")
                                        for d in hueco):
                t.hasta, t.dias = f, t.dias + 1
                continue
        tramos.append(TramoVacaciones(desde=f, hasta=f, dias=1, futuro=f > hoy))
    return list(reversed(tramos))


def saldo_vacaciones(dias: Mapping, cfg: Config, hoy: date) -> SaldoVacaciones:
    """Saldo de vacaciones: lo informado por RR.HH. menos los días marcados como «vacaciones»."""
    corte = to_date(cfg.vac_saldo_fecha) if cfg.vac_saldo_fecha else None
    fechas = [f for f, d in dias.items() if d.tipo == "vacaciones" and (corte is None or f >= corte)]
    tomados = sum(1 for f in fechas if f <= hoy)
    programados = len(fechas) - tomados
    configurado = cfg.vac_saldo_dias is not None and corte is not None
    inicial = float(cfg.vac_saldo_dias or 0)
    acumulado = (round(meses_completos(corte, hoy) * cfg.vac_dias_anuales / 12, 2)
                 if configurado and cfg.vac_acumular else 0.0)
    return SaldoVacaciones(
        configurado=configurado, corte=corte, saldo_inicial=inicial, acumulado=acumulado,
        tomados=tomados, programados=programados,
        disponibles=round(inicial + acumulado - tomados - programados, 2),
        tramos=tramos_vacaciones(fechas, dias, cfg, hoy),
    )
