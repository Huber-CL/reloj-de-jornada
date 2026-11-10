"""Resolución inteligente Entrada/Salida de las marcas Workera de un día.

El reloj físico a veces no permite cambiar el botón, así que pueden llegar dos "Entrada" o dos
"Salida" el mismo día. La secuencia cronológica manda sobre la etiqueta; el correo de alertas
(Tipo B) confirma o reconstruye las marcas. Ver CLAUDE.md § "Resolución Entrada/Salida".

Es una función pura: `resolver_dia(marcas, alerta, overrides)` se recalcula completa cada vez
que llega un correo nuevo para esa fecha (idempotente).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable, Mapping, Optional

from core.calculator import fmt_hms, parse_hms
from services.workera_parser import AlertaWorkera, MarcacionWorkera

INGRESO = "ingreso"
SALIDA = "salida"
REBOTE = "rebote"
INTERMEDIA = "intermedia"
PENDIENTE = "pendiente"
IGNORADA = "ignorada"           # estado ≠ Activo o descartada manualmente

M_DECLARADO = "declarado"       # se respetó la etiqueta del reloj
M_SECUENCIA = "secuencia"       # orden cronológico (min = ingreso, max = salida)
M_HORARIO = "horario"           # marca única clasificada por la hora del día
M_ALERTA = "alerta"             # confirmada por el correo de alertas de Workera
M_REBOTE = "rebote"
M_MANUAL = "manual"
M_ESTADO = "estado"

AV_FALTA_ENTRADA = "falta_entrada"
AV_FALTA_SALIDA = "falta_salida"
AV_MARCAS_CERCANAS = "marcas_cercanas_revisar"
AV_MARCAS_INTERMEDIAS = "marcas_intermedias"
AV_NO_CUADRA_ALERTA = "no_cuadra_con_alerta"


@dataclass
class ResolverConfig:
    debounce_min: int = 15
    min_separacion_h: float = 2.0
    corte_manana: str = "13:00"          # antes → ingreso
    corte_tarde: str = "14:00"           # desde aquí una marca única se evalúa como posible salida
    corte_salida_tipica: str = "15:00"   # 'Entrada' después de esta hora → preguntar
    tolerancia_alerta_s: int = 120       # Workera trunca a minutos


@dataclass
class Marca:
    checksum: str
    fecha: str
    hora: str
    tipo_declarado: str          # Entrada | Salida
    activa: bool = True

    @property
    def segundos(self) -> int:
        return parse_hms(self.hora)

    @classmethod
    def desde_correo(cls, m: MarcacionWorkera) -> "Marca":
        return cls(m.checksum, m.fecha, m.hora, m.tipo_marca_declarado, m.activa)


@dataclass
class Asignacion:
    checksum: str
    hora: str
    tipo_declarado: str
    rol: str
    metodo: str
    inferido_por_secuencia: bool = False
    confirmada_por_alerta: bool = False
    badge: Optional[str] = None


@dataclass
class Pregunta:
    checksum: str
    hora: str
    mensaje: str
    accion: str = "mover_a_salida"
    etiqueta_boton: str = "⇄ Mover a Salida"


@dataclass
class Sugerencia:
    campo: str          # ingreso | salida
    hora: str           # HH:MM:SS
    motivo: str


@dataclass
class Conciliacion:
    turno_inicio: str
    turno_fin: str
    ingreso_reconstruido: Optional[str] = None
    salida_reconstruida: Optional[str] = None
    ingreso_confirmado: bool = False
    salida_confirmada: bool = False
    jornada_validada: bool = False
    badge: str = ""


@dataclass
class ResolucionDia:
    fecha: str
    ingreso: Optional[str] = None
    salida: Optional[str] = None
    ingreso_checksum: Optional[str] = None
    salida_checksum: Optional[str] = None
    asignaciones: list[Asignacion] = field(default_factory=list)
    pregunta: Optional[Pregunta] = None
    sugerencias: list[Sugerencia] = field(default_factory=list)
    avisos: list[str] = field(default_factory=list)
    conciliacion: Optional[Conciliacion] = None

    def asignacion(self, checksum: str) -> Optional[Asignacion]:
        return next((a for a in self.asignaciones if a.checksum == checksum), None)

    def sugerencia(self, campo: str) -> Optional[Sugerencia]:
        return next((s for s in self.sugerencias if s.campo == campo), None)

    def campos_dia(self, aplicar_sugerencias: bool = False) -> dict:
        """Campos `ingreso`/`salida` para el documento days/<fecha>."""
        res = {"ingreso": self.ingreso, "salida": self.salida}
        if aplicar_sugerencias:
            for s in self.sugerencias:
                if res.get(s.campo) is None:
                    res[s.campo] = s.hora
        return res


# ----------------------------------------------------------------------------- helpers
def _badge_inferido(rol: str, declarado: str) -> Optional[str]:
    if rol == SALIDA and declarado != "Salida":
        return f"Salida inferida (reloj marcó {declarado})"
    if rol == INGRESO and declarado != "Entrada":
        return f"Entrada inferida (reloj marcó {declarado})"
    return None


def _asignar(a: Asignacion, rol: str, metodo: str) -> None:
    a.rol, a.metodo = rol, metodo
    badge = _badge_inferido(rol, a.tipo_declarado)
    a.inferido_por_secuencia = badge is not None and metodo != M_MANUAL
    a.badge = badge if metodo != M_MANUAL else "Ajuste manual"


def _rol_declarado(declarado: str) -> str:
    return SALIDA if declarado == "Salida" else INGRESO


def _hhmm(seg: int) -> str:
    return fmt_hms(seg, con_segundos=False)


def _badge_alerta(alerta: AlertaWorkera) -> str:
    partes = []
    etiquetas = {
        "sobretiempo_fin": "+{} min sobretiempo",
        "sobretiempo_inicio": "{} min entrada anticipada",
        "atraso_inicio": "+{} min atraso",
        "salida_anticipada": "-{} min salida anticipada",
    }
    for ev in alerta.alertas_detectadas:
        partes.append(etiquetas.get(ev.tipo, ev.tipo + " {} min").format(ev.minutos))
    detalle = " | ".join(partes) if partes else "sin alertas"
    return f"Workera: Turno {alerta.turno_inicio}-{alerta.turno_fin} | {detalle}"


# ----------------------------------------------------------------------------- algoritmo
def resolver_dia(marcas: Iterable[Marca | MarcacionWorkera], alerta: Optional[AlertaWorkera] = None,
                 overrides: Optional[Mapping[str, str]] = None,
                 config: Optional[ResolverConfig] = None, fecha: Optional[str] = None) -> ResolucionDia:
    cfg = config or ResolverConfig()
    lista = [m if isinstance(m, Marca) else Marca.desde_correo(m) for m in marcas]
    fecha = fecha or (lista[0].fecha if lista else alerta.fecha if alerta else "")
    res = ResolucionDia(fecha=fecha)

    # 1. Idempotencia por checksum y orden cronológico.
    unicas: dict[str, Marca] = {}
    for m in lista:
        if m.fecha == fecha:
            unicas.setdefault(m.checksum, m)
    ordenadas = sorted(unicas.values(), key=lambda m: (m.segundos, m.checksum))

    # 2. Estado y anti-rebote.
    validas: list[tuple[Marca, Asignacion]] = []
    for m in ordenadas:
        a = Asignacion(m.checksum, m.hora, m.tipo_declarado, rol="", metodo="")
        res.asignaciones.append(a)
        if not m.activa:
            a.rol, a.metodo, a.badge = IGNORADA, M_ESTADO, "Marca no activa en Workera"
            continue
        if validas and m.segundos - validas[-1][0].segundos < cfg.debounce_min * 60:
            previa = validas[-1][0]
            dif = m.segundos - previa.segundos
            a.rol, a.metodo = REBOTE, M_REBOTE
            a.badge = f"Duplicada: {dif // 60} min {dif % 60} s después de {previa.hora}"
            continue
        validas.append((m, a))

    # 3. Clasificación por secuencia.
    n = len(validas)
    if n == 1:
        _clasificar_unica(validas[0][0], validas[0][1], res, cfg)
    elif n == 2:
        (m1, a1), (m2, a2) = validas
        if m2.segundos - m1.segundos >= cfg.min_separacion_h * 3600:
            _asignar(a1, INGRESO, M_SECUENCIA)
            _asignar(a2, SALIDA, M_SECUENCIA)
        elif (m1.tipo_declarado, m2.tipo_declarado) == ("Entrada", "Salida"):
            _asignar(a1, INGRESO, M_DECLARADO)
            _asignar(a2, SALIDA, M_DECLARADO)
        else:
            _asignar(a1, INGRESO, M_SECUENCIA)
            _asignar(a2, SALIDA, M_SECUENCIA)
            res.avisos.append(AV_MARCAS_CERCANAS)
    elif n >= 3:
        _asignar(validas[0][1], INGRESO, M_SECUENCIA)
        _asignar(validas[-1][1], SALIDA, M_SECUENCIA)
        for _, a in validas[1:-1]:
            a.rol, a.metodo, a.badge = INTERMEDIA, M_SECUENCIA, "Marca intermedia"
        res.avisos.append(AV_MARCAS_INTERMEDIAS)

    # 4. Conciliación con el correo de alertas.
    if alerta and alerta.fecha == fecha:
        _conciliar(validas, alerta, res, cfg)

    # 5. Ajustes manuales del usuario (prioridad máxima).
    for checksum, rol in (overrides or {}).items():
        a = res.asignacion(checksum)
        if a is None or rol not in (INGRESO, SALIDA, IGNORADA):
            continue
        if rol == IGNORADA:
            a.rol, a.metodo, a.badge, a.inferido_por_secuencia = IGNORADA, M_MANUAL, "Descartada manualmente", False
        else:
            _asignar(a, rol, M_MANUAL)
        if res.pregunta and res.pregunta.checksum == checksum:
            res.pregunta = None

    _derivar(res)
    if res.conciliacion:
        _validar(res, alerta, cfg)
    return res


def _clasificar_unica(m: Marca, a: Asignacion, res: ResolucionDia, cfg: ResolverConfig) -> None:
    s = m.segundos
    if s < parse_hms(cfg.corte_manana):
        _asignar(a, INGRESO, M_HORARIO)
    elif s < parse_hms(cfg.corte_tarde):
        _asignar(a, _rol_declarado(m.tipo_declarado), M_DECLARADO)
    elif m.tipo_declarado == "Salida":
        _asignar(a, SALIDA, M_DECLARADO)
    elif s > parse_hms(cfg.corte_salida_tipica):
        a.rol, a.metodo = PENDIENTE, M_DECLARADO
        a.badge = "¿Entrada o Salida?"
        res.pregunta = Pregunta(
            checksum=m.checksum, hora=m.hora,
            mensaje=(f"Se detectó marca a las {_hhmm(s)} como 'Entrada'. "
                     "¿Es tu Salida de hoy o un turno de tarde?"),
        )
    else:
        _asignar(a, INGRESO, M_DECLARADO)       # turno de tarde (14:00–15:00)


def _mas_cercana(validas, objetivo: int, tolerancia: int) -> Optional[tuple[Marca, Asignacion]]:
    candidatas = [(abs(m.segundos - objetivo), m.segundos, (m, a)) for m, a in validas
                  if abs(m.segundos - objetivo) <= tolerancia]
    return min(candidatas, key=lambda c: (c[0], c[1]))[2] if candidatas else None


def _confirmar(validas, objetivo: int, rol: str, res: ResolucionDia, cfg: ResolverConfig) -> bool:
    encontrada = _mas_cercana(validas, objetivo, cfg.tolerancia_alerta_s)
    if not encontrada:
        return False
    marca, a = encontrada
    # Quien tuviera ese rol antes deja de tenerlo.
    for _, otra in validas:
        if otra is not a and otra.rol == rol:
            otra.rol, otra.metodo, otra.badge = INTERMEDIA, M_ALERTA, "Desplazada por alerta Workera"
    _asignar(a, rol, M_ALERTA)
    a.confirmada_por_alerta = True
    nombre = "Salida" if rol == SALIDA else "Entrada"
    a.badge = (f"{nombre} confirmada por Workera"
               + (f" (reloj marcó {a.tipo_declarado})" if a.inferido_por_secuencia else ""))
    if res.pregunta and res.pregunta.checksum == marca.checksum:
        res.pregunta = None
    return True


def _conciliar(validas, alerta: AlertaWorkera, res: ResolucionDia, cfg: ResolverConfig) -> None:
    inicio, fin = parse_hms(alerta.turno_inicio), parse_hms(alerta.turno_fin)
    c = Conciliacion(turno_inicio=alerta.turno_inicio, turno_fin=alerta.turno_fin,
                     badge=_badge_alerta(alerta))

    sal_rec = None
    if alerta.minutos("sobretiempo_fin") is not None:
        sal_rec = fin + alerta.minutos("sobretiempo_fin") * 60
    elif alerta.minutos("salida_anticipada") is not None:
        sal_rec = fin - alerta.minutos("salida_anticipada") * 60
    ing_rec = None
    if alerta.minutos("atraso_inicio") is not None:
        ing_rec = inicio + alerta.minutos("atraso_inicio") * 60
    elif alerta.minutos("sobretiempo_inicio") is not None:
        ing_rec = inicio - alerta.minutos("sobretiempo_inicio") * 60

    if sal_rec is not None:
        c.salida_reconstruida = fmt_hms(sal_rec)
        c.salida_confirmada = _confirmar(validas, sal_rec, SALIDA, res, cfg)
    if ing_rec is not None:
        c.ingreso_reconstruido = fmt_hms(ing_rec)
        c.ingreso_confirmado = _confirmar(validas, ing_rec, INGRESO, res, cfg)
    res.conciliacion = c


def _derivar(res: ResolucionDia) -> None:
    ingresos = [a for a in res.asignaciones if a.rol == INGRESO]
    salidas = [a for a in res.asignaciones if a.rol == SALIDA]
    if ingresos:
        a = min(ingresos, key=lambda x: parse_hms(x.hora))
        res.ingreso, res.ingreso_checksum = a.hora, a.checksum
    if salidas:
        a = max(salidas, key=lambda x: parse_hms(x.hora))
        res.salida, res.salida_checksum = a.hora, a.checksum
    if res.salida and not res.ingreso and AV_FALTA_ENTRADA not in res.avisos:
        res.avisos.append(AV_FALTA_ENTRADA)
    if res.ingreso and not res.salida and not res.pregunta and AV_FALTA_SALIDA not in res.avisos:
        res.avisos.append(AV_FALTA_SALIDA)


def _validar(res: ResolucionDia, alerta: AlertaWorkera, cfg: ResolverConfig) -> None:
    c = res.conciliacion
    # Autocompletado ofrecido (no aplicado) para la marca que falte.
    if res.salida is None and res.pregunta is None:
        if c.salida_reconstruida:
            res.sugerencias.append(Sugerencia(SALIDA, c.salida_reconstruida,
                                              f"Reconstruida: fin de turno {c.turno_fin} ± minutos de la alerta"))
        else:
            res.sugerencias.append(Sugerencia(SALIDA, fmt_hms(parse_hms(c.turno_fin)),
                                              "Según fin de turno oficial (sin alerta de salida)"))
    if res.ingreso is None:
        if c.ingreso_reconstruido:
            res.sugerencias.append(Sugerencia(INGRESO, c.ingreso_reconstruido,
                                              f"Reconstruida: inicio de turno {c.turno_inicio} ± minutos de la alerta"))
        else:
            res.sugerencias.append(Sugerencia(INGRESO, fmt_hms(parse_hms(c.turno_inicio)),
                                              "Según inicio de turno oficial (sin alerta de atraso)"))

    # La marca vigente debe calzar con la reconstrucción (si el usuario la editó, avisar).
    calza = True
    for real, rec in ((res.salida, c.salida_reconstruida), (res.ingreso, c.ingreso_reconstruido)):
        if real and rec and abs(parse_hms(real) - parse_hms(rec)) > cfg.tolerancia_alerta_s:
            calza = False
    if not calza:
        res.avisos.append(AV_NO_CUADRA_ALERTA)
    c.jornada_validada = bool(res.ingreso and res.salida and calza)


# ----------------------------------------------------------------------------- acciones de UI
def overrides_invertir(res: ResolucionDia, overrides: Optional[Mapping[str, str]] = None) -> dict[str, str]:
    """Botón '⇄ Invertir Entrada/Salida': intercambia los roles de ingreso y salida."""
    nuevos = dict(overrides or {})
    if res.ingreso_checksum:
        nuevos[res.ingreso_checksum] = SALIDA
    if res.salida_checksum:
        nuevos[res.salida_checksum] = INGRESO
    return nuevos


def overrides_mover_a_salida(checksum: str, overrides: Optional[Mapping[str, str]] = None) -> dict[str, str]:
    """Botón '⇄ Mover a Salida' del banner de pregunta."""
    nuevos = dict(overrides or {})
    nuevos[checksum] = SALIDA
    return nuevos


def agrupar_por_fecha(marcas: Iterable[Marca | MarcacionWorkera]) -> dict[str, list[Marca]]:
    grupos: dict[str, list[Marca]] = {}
    for m in marcas:
        marca = m if isinstance(m, Marca) else Marca.desde_correo(m)
        grupos.setdefault(marca.fecha, []).append(marca)
    return grupos
