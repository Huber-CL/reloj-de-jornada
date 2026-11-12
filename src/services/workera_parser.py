"""Parser de correos de Workera.

Tipo A: "Notificación: Nuevos registros de asistencia - DD/MM/AAAA"  → MarcacionWorkera
Tipo B: "Alertas de asistencia automáticas - [día] DD/MM/AAAA"       → AlertaWorkera
Tipo C: "Solicitud de marcación aceptada" (RR.HH. registra una marca olvidada) → MarcacionWorkera

Solo stdlib (html.parser + email) para que el build de Android no arrastre extensiones C.
La extracción primero lee las tablas HTML (filas etiqueta | valor) y, si falta algo, cae a
expresiones regulares sobre el texto plano del correo.
"""
from __future__ import annotations

import hashlib
import re
import unicodedata
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from email import policy
from email.message import EmailMessage
from email.parser import BytesParser
from email.utils import parseaddr
from html.parser import HTMLParser
from typing import Optional, Union

WORKERA_SENDER = "notificaciones@workera.com"
WORKERA_DOMAIN = "workera.com"
TIPO_A = "A"
TIPO_B = "B"
TIPO_C = "C"


class WorkeraParseError(ValueError):
    """El correo parece de Workera pero le faltan datos obligatorios."""


# ----------------------------------------------------------------------------- texto
def normalizar(texto: str) -> str:
    """Minúsculas, sin acentos y con espacios colapsados (para comparar y aplicar regex)."""
    sin_acentos = "".join(c for c in unicodedata.normalize("NFKD", texto or "")
                          if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", sin_acentos.replace("\xa0", " ")).strip().lower()


def _limpiar(texto: str) -> str:
    return re.sub(r"\s+", " ", (texto or "").replace("\xa0", " ")).strip()


class _HtmlTablas(HTMLParser):
    """Extrae filas de tablas (soporta tablas anidadas de maquetación) y el texto visible."""

    _BLOQUE = {"p", "div", "br", "tr", "td", "th", "li", "table", "h1", "h2", "h3", "h4", "h5", "h6"}
    _OCULTO = {"script", "style", "head", "title"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.filas: list[list[str]] = []
        self._filas: list[list[str]] = []
        self._celdas: list[list[str]] = []
        self._texto: list[str] = []
        self._oculto = 0

    def handle_starttag(self, tag, attrs):
        if tag in self._OCULTO:
            self._oculto += 1
            return
        if tag == "tr":
            self._filas.append([])
        elif tag in ("td", "th"):
            self._celdas.append([])
        elif tag == "br" and self._celdas:
            self._celdas[-1].append(" ")
        if tag in self._BLOQUE:
            self._texto.append("\n")

    def handle_endtag(self, tag):
        if tag in self._OCULTO:
            self._oculto = max(0, self._oculto - 1)
            return
        if tag in ("td", "th") and self._celdas:
            celda = _limpiar("".join(self._celdas.pop()))
            if self._filas:
                self._filas[-1].append(celda)
        elif tag == "tr" and self._filas:
            fila = self._filas.pop()
            if any(fila):
                self.filas.append(fila)
        if tag in self._BLOQUE:
            self._texto.append("\n")

    def handle_data(self, data):
        if self._oculto:
            return
        self._texto.append(data)
        if self._celdas:
            self._celdas[-1].append(data)

    @property
    def texto(self) -> str:
        lineas = (_limpiar(l) for l in "".join(self._texto).split("\n"))
        return "\n".join(l for l in lineas if l)


def _analizar_html(contenido: str) -> tuple[list[list[str]], str]:
    p = _HtmlTablas()
    p.feed(contenido or "")
    p.close()
    return p.filas, p.texto


def _pares_etiqueta_valor(filas: list[list[str]], etiquetas: dict[str, str]) -> dict[str, str]:
    """Recorre las filas buscando celdas-etiqueta conocidas; el valor es la celda siguiente.
    Ante etiquetas repetidas gana la primera aparición (p. ej. 'Nombre' del trabajador)."""
    res: dict[str, str] = {}
    for fila in filas:
        for i in range(len(fila) - 1):
            campo = etiquetas.get(normalizar(fila[i]).rstrip(":").strip())
            if campo and campo not in res and fila[i + 1].strip():
                res[campo] = fila[i + 1].strip()
    return res


def _pares_en_lineas(texto: str, etiquetas: dict[str, str], res: dict[str, str]) -> None:
    """Versión texto plano: líneas 'Etiqueta: valor'. Solo completa campos que falten."""
    for linea in texto.splitlines():
        etiqueta, sep, valor = linea.partition(":")
        campo = etiquetas.get(normalizar(etiqueta)) if sep else None
        if campo and campo not in res and valor.strip():
            res[campo] = valor.strip()


# ----------------------------------------------------------------------------- RUT
def normalizar_rut(rut: str) -> str:
    """'12.345.678-5' / '123456785' → '12345678-5' (DV en mayúscula)."""
    limpio = re.sub(r"[^0-9kK]", "", rut or "").upper()
    if len(limpio) < 2:
        return ""
    return f"{limpio[:-1]}-{limpio[-1]}"


def digito_verificador(cuerpo: str) -> str:
    suma, mult = 0, 2
    for d in reversed(cuerpo):
        suma += int(d) * mult
        mult = 2 if mult == 7 else mult + 1
    dv = 11 - suma % 11
    return {10: "K", 11: "0"}.get(dv, str(dv))


def rut_valido(rut: str) -> bool:
    n = normalizar_rut(rut)
    if not n:
        return False
    cuerpo, dv = n.split("-")
    return cuerpo.isdigit() and digito_verificador(cuerpo) == dv


def formatear_rut(rut: str) -> str:
    n = normalizar_rut(rut)
    if not n:
        return ""
    cuerpo, dv = n.split("-")
    return f"{int(cuerpo):,}".replace(",", ".") + f"-{dv}"


def mismo_rut(a: str, b: str) -> bool:
    na, nb = normalizar_rut(a), normalizar_rut(b)
    return bool(na) and na == nb


# ----------------------------------------------------------------------------- modelos
@dataclass
class MarcacionWorkera:
    """Correo Tipo A."""

    fecha: str                      # AAAA-MM-DD
    hora: str                       # HH:MM:SS
    tipo_marca_declarado: str       # Entrada | Salida
    checksum: str
    direccion: str = ""
    dispositivo: str = ""
    estado: str = ""
    rut_trabajador: str = ""
    nombre_trabajador: str = ""
    raw_text: str = ""
    tipo_correo: str = TIPO_A

    @property
    def activa(self) -> bool:
        return not self.estado or normalizar(self.estado) == "activo"

    def pertenece_a(self, rut_configurado: str) -> Optional[bool]:
        if not self.rut_trabajador or not rut_configurado:
            return None
        return mismo_rut(self.rut_trabajador, rut_configurado)


@dataclass
class EventoAlerta:
    tipo: str          # sobretiempo_fin | sobretiempo_inicio | atraso_inicio | salida_anticipada
    minutos: int
    texto: str


@dataclass
class AlertaWorkera:
    """Correo Tipo B."""

    fecha: str                      # AAAA-MM-DD
    turno_inicio: str               # HH:MM
    turno_fin: str                  # HH:MM
    run_trabajador: str = ""
    nombre_trabajador: str = ""
    hora_alerta: Optional[str] = None   # ISO 8601 con offset
    alertas_detectadas: list[EventoAlerta] = field(default_factory=list)
    raw_text: str = ""
    tipo_correo: str = TIPO_B

    @property
    def clave(self) -> str:
        return f"ALERTA-{self.fecha}"

    def minutos(self, tipo: str) -> Optional[int]:
        for ev in self.alertas_detectadas:
            if ev.tipo == tipo:
                return ev.minutos
        return None

    def pertenece_a(self, rut_configurado: str) -> Optional[bool]:
        if not self.run_trabajador or not rut_configurado:
            return None
        return mismo_rut(self.run_trabajador, rut_configurado)


# ----------------------------------------------------------------------------- conversiones
def _fecha_iso(ddmmaaaa: str) -> str:
    m = re.search(r"(\d{1,2})/(\d{1,2})/(\d{4})", ddmmaaaa or "")
    if not m:
        raise WorkeraParseError(f"Fecha inválida: {ddmmaaaa!r}")
    try:
        return datetime(int(m[3]), int(m[2]), int(m[1])).date().isoformat()
    except ValueError as exc:
        raise WorkeraParseError(f"Fecha inválida: {ddmmaaaa!r}") from exc


def _hora_hms(texto: str) -> str:
    m = re.search(r"(\d{1,2}):(\d{2})(?::(\d{2}))?", texto or "")
    if not m:
        raise WorkeraParseError(f"Hora inválida: {texto!r}")
    h, mi, s = int(m[1]), int(m[2]), int(m[3] or 0)
    if not (h < 24 and mi < 60 and s < 60):
        raise WorkeraParseError(f"Hora fuera de rango: {texto!r}")
    return f"{h:02d}:{mi:02d}:{s:02d}"


def _hora_alerta_iso(texto: str) -> Optional[str]:
    m = re.search(r"(\d{2}/\d{2}/\d{4})\s+(\d{1,2}:\d{2}(?::\d{2})?)"
                  r"(?:\s*\(\s*GMT\s*([+-])(\d{1,2}):?(\d{2})\s*\))?", texto or "")
    if not m:
        return None
    fecha = _fecha_iso(m[1])
    dt = datetime.fromisoformat(f"{fecha}T{_hora_hms(m[2])}")
    if m[3]:
        signo = -1 if m[3] == "-" else 1
        dt = dt.replace(tzinfo=timezone(signo * timedelta(hours=int(m[4]), minutes=int(m[5]))))
    return dt.isoformat()


# ----------------------------------------------------------------------------- Tipo A
_ETIQUETAS_A = {
    "fecha registro": "fecha",
    "hora registro": "hora",
    "direccion": "direccion",
    "tipo de marcacion": "tipo",
    "dispositivo asociado": "dispositivo",
    "estado registro": "estado",
    "hash (checksum)": "checksum",
    "hash": "checksum",
    "checksum": "checksum",
    "rut": "rut",
    "r.u.t.": "rut",
    "r.u.n.": "rut",
    "nombre completo": "nombre",
}

# Respaldo sobre texto normalizado cuando el correo no trae tablas (versión texto plano).
_RESPALDO_A = {
    "fecha": r"fecha registro:? (\d{1,2}/\d{1,2}/\d{4})",
    "hora": r"hora registro:? (\d{1,2}:\d{2}(?::\d{2})?)",
    "tipo": r"tipo de marcacion:? (entrada|salida)",
    "checksum": r"hash(?: \(checksum\))?:? ([0-9a-z]+)",
    "rut": r"\brut:? ([0-9.]+-[0-9k])",
    "estado": r"estado registro:? (\w+)",
}


def parse_marcacion_html(contenido: str) -> MarcacionWorkera:
    filas, texto = _analizar_html(contenido)
    datos = _pares_etiqueta_valor(filas, _ETIQUETAS_A)
    _pares_en_lineas(texto, _ETIQUETAS_A, datos)
    plano = normalizar(texto)
    for campo, patron in _RESPALDO_A.items():
        if campo not in datos:
            m = re.search(patron, plano)
            if m:
                datos[campo] = m[1]

    faltan = [c for c in ("fecha", "hora", "tipo", "checksum") if not datos.get(c)]
    if faltan:
        raise WorkeraParseError(f"Correo de marcación sin: {', '.join(faltan)}")

    tipo = normalizar(datos["tipo"])
    if tipo not in ("entrada", "salida"):
        raise WorkeraParseError(f"Tipo de marcación desconocido: {datos['tipo']!r}")
    checksum = re.sub(r"\s+", "", datos["checksum"]).upper()
    if not re.fullmatch(r"[0-9A-Z]+", checksum):
        raise WorkeraParseError(f"Checksum inválido: {datos['checksum']!r}")

    return MarcacionWorkera(
        fecha=_fecha_iso(datos["fecha"]),
        hora=_hora_hms(datos["hora"]),
        tipo_marca_declarado=tipo.capitalize(),
        checksum=checksum,
        direccion=datos.get("direccion", ""),
        dispositivo=datos.get("dispositivo", ""),
        estado=datos.get("estado", "").capitalize(),
        rut_trabajador=formatear_rut(datos.get("rut", "")) if datos.get("rut") else "",
        nombre_trabajador=datos.get("nombre", ""),
        raw_text=texto,
    )


# ----------------------------------------------------------------------------- Tipo B
_ETIQUETAS_B = {
    "r.u.n.": "run",
    "run": "run",
    "nombre": "nombre",
    "hora generacion alerta": "hora_alerta",
}

RE_HORARIO = re.compile(
    r"Horario:\s*(\d{1,2}:\d{2})\s*a\s*(\d{1,2}:\d{2}).*?Fecha:\s*(\d{2}/\d{2}/\d{4})",
    re.IGNORECASE | re.DOTALL,
)

# Se aplican sobre texto normalizado (minúsculas, sin acentos).
PATRONES_ALERTA: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("sobretiempo_fin", re.compile(r"sobretiempo de (\d+) minutos? en el termino de la jornada")),
    ("sobretiempo_inicio", re.compile(r"sobretiempo de (\d+) minutos? en el inicio")),
    ("atraso_inicio", re.compile(r"(?:atraso|demora|retraso) de (\d+) minutos? en el inicio")),
    ("salida_anticipada", re.compile(r"(?:salida anticipada|adelanto) de (\d+) minutos?")),
)


def parse_alerta_html(contenido: str) -> AlertaWorkera:
    filas, texto = _analizar_html(contenido)
    datos = _pares_etiqueta_valor(filas, _ETIQUETAS_B)
    plano_linea = _limpiar(texto)

    m = RE_HORARIO.search(plano_linea)
    if not m:
        raise WorkeraParseError("Correo de alerta sin 'Horario: HH:MM a HH:MM ... Fecha: DD/MM/AAAA'")
    turno_inicio, turno_fin = _hora_hms(m[1])[:5], _hora_hms(m[2])[:5]
    fecha = _fecha_iso(m[3])

    if "run" not in datos:
        r = re.search(r"R\.?U\.?N\.?:?\s*([0-9.]+-[0-9kK])", plano_linea)
        if r:
            datos["run"] = r[1]
    hora_alerta = _hora_alerta_iso(datos.get("hora_alerta", ""))
    if hora_alerta is None:
        r = re.search(r"Hora generaci[oó]n alerta:?\s*(.{10,40}?\))", plano_linea, re.IGNORECASE)
        hora_alerta = _hora_alerta_iso(r[1]) if r else None

    normal = normalizar(texto)
    eventos = [EventoAlerta(tipo, int(x[1]), x[0])
               for tipo, patron in PATRONES_ALERTA for x in patron.finditer(normal)]

    return AlertaWorkera(
        fecha=fecha, turno_inicio=turno_inicio, turno_fin=turno_fin,
        run_trabajador=formatear_rut(datos["run"]) if datos.get("run") else "",
        nombre_trabajador=datos.get("nombre", ""), hora_alerta=hora_alerta,
        alertas_detectadas=eventos, raw_text=texto,
    )


# ----------------------------------------------------------------------------- Tipo C
_ETIQUETAS_C = {
    "requerimiento": "requerimiento",
    "tipo de marcacion solicitada": "tipo",
    "tipo de marcacion": "tipo",
    "fecha/hora marcacion solicitada": "fecha_hora",
    "fecha/hora marcacion": "fecha_hora",
    "fecha y hora marcacion solicitada": "fecha_hora",
    "estado": "estado",
}

_RESPALDO_C = {
    "requerimiento": r"requerimiento:? (creacion de marcacion|modificacion de marcacion|eliminacion de marcacion)",
    "tipo": r"tipo de marcacion solicitada:? (entrada|salida)",
    "fecha_hora": r"fecha/hora marcacion solicitada:? (\d{1,2}/\d{1,2}/\d{4} \d{1,2}:\d{2}(?::\d{2})?)",
    "estado": r"\bestado:? (aceptad[oa]|rechazad[oa]|pendiente)",
}


def checksum_solicitud(fecha: str, hora: str, tipo: str) -> str:
    """Las solicitudes no traen hash: se arma uno estable para que reimportar el correo no duplique."""
    return "SOL" + hashlib.sha1(f"{fecha}T{hora}|{tipo}".encode()).hexdigest()[:20].upper()


def parse_solicitud_html(contenido: str) -> Optional[MarcacionWorkera]:
    """Correo «Solicitud de marcación aceptada/rechazada». Devuelve la marca creada por RR.HH.,
    o None si el requerimiento no es una creación de marcación (modificación/eliminación: aún no
    se conoce su formato, se ignoran)."""
    filas, texto = _analizar_html(contenido)
    datos = _pares_etiqueta_valor(filas, _ETIQUETAS_C)
    _pares_en_lineas(texto, _ETIQUETAS_C, datos)
    plano = normalizar(texto)
    for campo, patron in _RESPALDO_C.items():
        if campo not in datos:
            m = re.search(patron, plano)
            if m:
                datos[campo] = m[1]

    requerimiento = normalizar(datos.get("requerimiento", ""))
    if requerimiento and "creacion" not in requerimiento:
        return None
    faltan = [c for c in ("tipo", "fecha_hora") if not datos.get(c)]
    if faltan:
        raise WorkeraParseError(f"Solicitud de marcación sin: {', '.join(faltan)}")
    tipo = normalizar(datos["tipo"])
    if tipo not in ("entrada", "salida"):
        raise WorkeraParseError(f"Tipo de marcación desconocido: {datos['tipo']!r}")
    fecha, hora = _fecha_iso(datos["fecha_hora"]), _hora_hms(datos["fecha_hora"].split(" ", 1)[-1])
    estado = normalizar(datos.get("estado", ""))
    aceptada = estado.startswith("aceptad") or (not estado and "solicitud de marcacion aceptada" in plano)
    m = re.search(r"estimad[oa] trabajador[a]?:?\s*\n([^\n]+)", texto, re.IGNORECASE)
    return MarcacionWorkera(
        fecha=fecha, hora=hora, tipo_marca_declarado=tipo.capitalize(),
        checksum=checksum_solicitud(fecha, hora, tipo),
        dispositivo="Solicitud aceptada por RR.HH." if aceptada else "Solicitud no aceptada",
        estado="Activo" if aceptada else (datos.get("estado") or "Pendiente").capitalize(),
        nombre_trabajador=m[1].strip() if m else "",
        raw_text=texto, tipo_correo=TIPO_C,
    )


# ----------------------------------------------------------------------------- correo completo
def clasificar(asunto: str = "", texto: str = "") -> Optional[str]:
    a, t = normalizar(asunto), normalizar(texto)
    if "nuevos registros de asistencia" in a:
        return TIPO_A
    if "alertas de asistencia" in a:
        return TIPO_B
    if "solicitud de marcacion" in a:
        return TIPO_C
    if "hash (checksum)" in t or "nuevos registros de asistencia" in t:
        return TIPO_A
    if "hora generacion alerta" in t or "alertas de asistencia" in t:
        return TIPO_B
    if "solicitud de marcacion" in t and "marcacion solicitada" in t:
        return TIPO_C
    return None


def parse_contenido(contenido: str, asunto: str = "") -> Union[MarcacionWorkera, AlertaWorkera, None]:
    """Parsea el HTML (o texto) de un correo Workera, clasificándolo por asunto o contenido.
    Devuelve None para solicitudes que no crean una marca (se ignoran)."""
    tipo = clasificar(asunto, _analizar_html(contenido)[1])
    if tipo == TIPO_A:
        return parse_marcacion_html(contenido)
    if tipo == TIPO_B:
        return parse_alerta_html(contenido)
    if tipo == TIPO_C:
        return parse_solicitud_html(contenido)
    raise WorkeraParseError("No es un correo de marcación ni de alertas de Workera")


@dataclass
class CorreoWorkera:
    tipo: str
    datos: Union[MarcacionWorkera, AlertaWorkera]
    asunto: str
    remitente: str
    message_id: str
    remitente_valido: bool
    dkim_ok: Optional[bool]


_RE_DKIM = re.compile(r"dkim=pass[^;]*header\.[id]=@?(?:[\w-]+\.)*workera\.com", re.IGNORECASE)


def parse_email(raw: Union[bytes, EmailMessage]) -> Optional[CorreoWorkera]:
    """Parsea un mensaje RFC 822 completo. Devuelve None si no es un correo Workera reconocible."""
    msg = raw if isinstance(raw, EmailMessage) else BytesParser(policy=policy.default).parsebytes(raw)
    asunto = str(msg.get("subject", ""))
    remitente = parseaddr(str(msg.get("from", "")))[1].lower()
    cuerpo = msg.get_body(preferencelist=("html", "plain"))
    if cuerpo is None:
        return None
    contenido = cuerpo.get_content()
    if cuerpo.get_content_subtype() == "plain":
        contenido = contenido.replace("<", "&lt;")   # que html.parser lo trate como texto
    try:
        datos = parse_contenido(contenido, asunto)
    except WorkeraParseError:
        if clasificar(asunto):
            raise
        return None
    if datos is None:
        return None

    auth = " ".join(str(v) for v in (msg.get_all("authentication-results") or []))
    return CorreoWorkera(
        tipo=datos.tipo_correo, datos=datos, asunto=asunto, remitente=remitente,
        message_id=str(msg.get("message-id", "")),
        remitente_valido=remitente == WORKERA_SENDER or remitente.endswith("@" + WORKERA_DOMAIN),
        dkim_ok=bool(_RE_DKIM.search(auth)) if auth else None,
    )
