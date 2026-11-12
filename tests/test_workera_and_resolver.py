"""Parser de correos Workera + resolución Entrada/Salida + conciliación con alertas."""
from __future__ import annotations

from datetime import date

import pytest

from core.calculator import Config, Day, calc_dia, fmt_duracion
from services.attendance_resolver import (
    AV_FALTA_ENTRADA, AV_FALTA_SALIDA, AV_MARCAS_INTERMEDIAS, IGNORADA, INGRESO, INTERMEDIA,
    M_ALERTA, M_HORARIO, M_MANUAL, M_SECUENCIA, PENDIENTE, REBOTE, SALIDA, Marca, ResolverConfig,
    agrupar_por_fecha, overrides_invertir, overrides_mover_a_salida, resolver_dia,
)
from services.imap_client import ImapSettings, WorkeraMailbox, fecha_imap
from services.workera_parser import (
    TIPO_A, TIPO_B, WorkeraParseError, formatear_rut, mismo_rut, parse_alerta_html, parse_contenido,
    parse_email, parse_marcacion_html, rut_valido,
)
from tests.fixtures.workera_html import (
    ITEM_ATRASO, ITEM_SALIDA_ANTICIPADA, ITEM_SOBRETIEMPO_FIN, RUT_OTRO, RUT_PRUEBA, email_bytes,
    html_alerta, html_marcacion, texto_marcacion_plano,
)


def marca(hora, tipo="Entrada", checksum=None, fecha="2026-11-06", activa=True):
    return Marca(checksum or f"H{hora.replace(':', '')}", fecha, hora, tipo, activa)


def alerta_106(items=(ITEM_SOBRETIEMPO_FIN.format(103),), inicio="07:00", fin="16:00"):
    return parse_alerta_html(html_alerta(items=items, inicio=inicio, fin=fin))


# =============================================================================== Correo Tipo A
class TestCorreoMarcacion:
    def test_correo_a_normal(self):
        m = parse_marcacion_html(html_marcacion())
        assert m.fecha == "2026-11-09"
        assert m.hora == "05:52:47"
        assert m.tipo_marca_declarado == "Entrada"
        assert m.checksum == "E7B8C5E7"
        assert m.direccion == "Calle Ejemplo 123"
        assert m.dispositivo == "RELOJ-01 (SPK0000000001)"
        assert m.estado == "Activo" and m.activa
        assert m.rut_trabajador == "12.345.678-5"
        assert m.pertenece_a(RUT_PRUEBA) is True
        assert m.tipo_correo == TIPO_A

    def test_rut_de_otro_trabajador_no_coincide(self):
        m = parse_marcacion_html(html_marcacion(rut=RUT_OTRO))
        assert m.pertenece_a(RUT_PRUEBA) is False
        assert m.pertenece_a("") is None          # RUT aún no configurado

    def test_version_texto_plano(self):
        m = parse_contenido(texto_marcacion_plano(tipo="Salida", hash_="ab12cd34"))
        assert (m.fecha, m.hora, m.tipo_marca_declarado, m.checksum) == ("2026-11-09", "05:52:47", "Salida", "AB12CD34")
        assert m.direccion == "Calle Ejemplo 123"

    def test_estado_no_activo(self):
        assert not parse_marcacion_html(html_marcacion(estado="Anulado")).activa

    def test_sin_checksum_es_error(self):
        html = html_marcacion().replace("Hash (checksum)", "Otro dato").replace("E7B8C5E7", "")
        with pytest.raises(WorkeraParseError, match="checksum"):
            parse_marcacion_html(html)

    def test_tipo_desconocido_es_error(self):
        with pytest.raises(WorkeraParseError):
            parse_marcacion_html(html_marcacion(tipo="Colación"))


# =============================================================================== Correo Tipo B
class TestCorreoAlerta:
    def test_correo_b_alerta(self):
        a = alerta_106()
        assert a.tipo_correo == TIPO_B
        assert a.fecha == "2026-11-06"
        assert (a.turno_inicio, a.turno_fin) == ("07:00", "16:00")
        assert a.run_trabajador == "12.345.678-5"
        assert a.nombre_trabajador == "TRABAJADOR DE PRUEBA"      # no el de la compañía
        assert a.hora_alerta == "2026-11-06T20:03:47-03:00"
        assert a.minutos("sobretiempo_fin") == 103
        assert a.pertenece_a(RUT_PRUEBA) is True

    @pytest.mark.parametrize("item, tipo, minutos", [
        (ITEM_ATRASO.format(12), "atraso_inicio", 12),
        ("Se registra una demora de 5 minutos en el inicio de la jornada.", "atraso_inicio", 5),
        ("Se registra un retraso de 1 minuto en el inicio de la jornada.", "atraso_inicio", 1),
        (ITEM_SALIDA_ANTICIPADA.format(30), "salida_anticipada", 30),
        ("Se registra un adelanto de 45 minutos en la salida.", "salida_anticipada", 45),
        ("Se registra un sobretiempo de 20 minutos en el inicio de la jornada.", "sobretiempo_inicio", 20),
        ("Se registra un SOBRETIEMPO DE 7 MINUTOS en el TÉRMINO de la jornada.", "sobretiempo_fin", 7),
    ])
    def test_regex_flexible(self, item, tipo, minutos):
        a = alerta_106(items=(item,))
        assert [(e.tipo, e.minutos) for e in a.alertas_detectadas] == [(tipo, minutos)]

    def test_varias_alertas_en_un_correo(self):
        a = alerta_106(items=(ITEM_ATRASO.format(10), ITEM_SOBRETIEMPO_FIN.format(30)))
        assert a.minutos("atraso_inicio") == 10 and a.minutos("sobretiempo_fin") == 30

    def test_sin_horario_es_error(self):
        with pytest.raises(WorkeraParseError, match="Horario"):
            parse_alerta_html(html_alerta().replace("Horario:", "Turno:"))


# =============================================================================== MIME / RUT / IMAP
class TestCorreoCompletoYUtilidades:
    def test_parse_email_mime_quoted_printable(self):
        raw = email_bytes(html_marcacion(), "Notificación: Nuevos registros de asistencia - 09/11/2026",
                          auth_results="mx.google.com; dkim=pass header.i=@workera.com; spf=pass")
        c = parse_email(raw)
        assert c.tipo == TIPO_A and c.datos.checksum == "E7B8C5E7"
        assert c.remitente_valido is True and c.dkim_ok is True

    def test_parse_email_alerta_y_remitente_falso(self):
        raw = email_bytes(html_alerta(), "Alertas de asistencia automáticas - viernes 06/11/2026",
                          remitente="Falso <notificaciones@workera.com.phish.io>")
        c = parse_email(raw)
        assert c.tipo == TIPO_B and c.datos.minutos("sobretiempo_fin") == 103
        assert c.remitente_valido is False and c.dkim_ok is None

    def test_parse_email_ajeno_devuelve_none(self):
        assert parse_email(email_bytes("<p>Hola</p>", "Reunión del lunes")) is None

    def test_rut(self):
        assert rut_valido("12.345.678-5") and rut_valido("20000003k")
        assert not rut_valido("12.345.678-6")
        assert mismo_rut("12345678-5", "12.345.678-5")
        assert formatear_rut("123456789k") == "123.456.789-K"

    def test_imap_solo_lectura_y_filtro(self):
        llamadas = []

        class FakeImap:
            def __init__(self, host, port):
                llamadas.append(("conn", host, port))

            def login(self, u, p):
                llamadas.append(("login", u, len(p), " " in p))

            def select(self, carpeta, readonly=False):
                llamadas.append(("select", carpeta, readonly))
                return ("OK", [b"2"]) if carpeta == '"02_Reloj_Control"' else ("NO", [])

            def uid(self, cmd, *args):
                llamadas.append(("uid", cmd) + tuple(a for a in args if a is not None))
                if cmd == "SEARCH":
                    return "OK", [b"10 11"]
                return "OK", [(b"11 (BODY[] {3}", b"raw"), b")"]

            def logout(self):
                llamadas.append(("logout",))

        cred = "abcd efgh ijkl mnop"  # security-scan: ignore (contraseña ficticia del test)
        caja = WorkeraMailbox(ImapSettings("usuario@example.com", cred), imap_factory=FakeImap)
        assert "abcd" not in repr(caja.settings)
        res = caja.descargar(desde=date(2026, 11, 9), uids_vistos={"10"})
        assert res == [("11", b"raw")]
        assert ("conn", "imap.gmail.com", 993) in llamadas
        assert ("login", "usuario@example.com", 16, False) in llamadas      # sin espacios
        assert ("select", '"02_Reloj_Control"', True) in llamadas
        assert ("uid", "SEARCH", "FROM", '"workera.com"', "SINCE", "09-Nov-2026") in llamadas
        assert ("uid", "FETCH", "11", "(BODY.PEEK[])") in llamadas
        assert llamadas[-1] == ("logout",)

    def test_fecha_imap_independiente_del_locale(self):
        assert fecha_imap(date(2026, 1, 5)) == "05-Jan-2026"


# =============================================================================== Resolver
class TestResolver:
    def test_correo_a_normal_se_asigna_como_ingreso(self):
        m = parse_marcacion_html(html_marcacion())
        r = resolver_dia([m])
        assert r.ingreso == "05:52:47" and r.salida is None
        assert r.asignacion("E7B8C5E7").metodo == M_HORARIO
        assert AV_FALTA_SALIDA in r.avisos

    def test_doble_entrada_la_segunda_es_salida(self):
        r = resolver_dia([marca("17:43:15", "Entrada", "BBB222"), marca("07:00:10", "Entrada", "AAA111")])
        assert (r.ingreso, r.salida) == ("07:00:10", "17:43:15")
        assert (r.ingreso_checksum, r.salida_checksum) == ("AAA111", "BBB222")
        b = r.asignacion("BBB222")
        assert b.rol == SALIDA and b.metodo == M_SECUENCIA
        assert b.inferido_por_secuencia is True
        assert b.badge == "Salida inferida (reloj marcó Entrada)"
        a = r.asignacion("AAA111")
        assert a.inferido_por_secuencia is False and a.badge is None

    def test_doble_entrada_desde_correos_html(self):
        correos = [parse_marcacion_html(html_marcacion(fecha="06/11/2026", hora=h, hash_=k))
                   for h, k in (("07:00:10", "AAA111"), ("17:43:15", "BBB222"))]
        r = resolver_dia(correos)
        assert r.salida_checksum == "BBB222" and r.asignacion("BBB222").inferido_por_secuencia

    def test_doble_salida_la_primera_es_ingreso(self):
        r = resolver_dia([marca("07:02:00", "Salida"), marca("16:30:00", "Salida")])
        assert (r.ingreso, r.salida) == ("07:02:00", "16:30:00")
        assert r.asignacion("H070200").badge == "Entrada inferida (reloj marcó Salida)"
        assert r.asignacion("H163000").inferido_por_secuencia is False

    @pytest.mark.parametrize("segunda, es_rebote", [
        ("07:05:10", True),     # 5 min  (< 10 min)
        ("07:09:59", True),     # < 10 min
        ("07:14:00", True),     # < 15 min (umbral configurado)
        ("07:15:10", False),    # justo 15 min → válida
    ])
    def test_anti_rebote(self, segunda, es_rebote):
        r = resolver_dia([marca("07:00:10", checksum="AAA111"), marca(segunda, checksum="CCC333")])
        a = r.asignacion("CCC333")
        assert (a.rol == REBOTE) is es_rebote
        assert len(r.asignaciones) == 2          # el rebote queda en el log crudo
        assert r.ingreso == "07:00:10"

    def test_rebote_configurable_10_min(self):
        r = resolver_dia([marca("07:00:10", checksum="A1"), marca("07:12:00", checksum="A2")],
                         config=ResolverConfig(debounce_min=10))
        assert r.asignacion("A2").rol != REBOTE

    def test_rebote_no_impide_detectar_salida(self):
        r = resolver_dia([marca("07:00:10", checksum="A1"), marca("07:03:00", checksum="A2"),
                          marca("17:00:00", checksum="A3")])
        assert (r.ingreso, r.salida) == ("07:00:10", "17:00:00")
        assert r.asignacion("A2").rol == REBOTE

    def test_idempotencia_por_checksum(self):
        r = resolver_dia([marca("07:00:10", checksum="AAA111")] * 3)
        assert len(r.asignaciones) == 1

    def test_marca_no_activa_se_ignora(self):
        r = resolver_dia([marca("07:00:00", checksum="X1", activa=False), marca("08:00:00", checksum="X2")])
        assert r.asignacion("X1").rol == IGNORADA and r.ingreso == "08:00:00"

    def test_unica_salida_por_la_tarde(self):
        r = resolver_dia([marca("16:30:00", "Salida")])
        assert r.salida == "16:30:00" and r.ingreso is None
        assert AV_FALTA_ENTRADA in r.avisos

    def test_unica_entrada_14_a_15_es_turno_tarde(self):
        r = resolver_dia([marca("14:30:00", "Entrada")])
        assert r.ingreso == "14:30:00" and r.pregunta is None

    def test_unica_entrada_despues_de_15_pregunta(self):
        r = resolver_dia([marca("17:43:15", "Entrada", "BBB222")])
        assert r.ingreso is None and r.salida is None
        assert r.asignacion("BBB222").rol == PENDIENTE
        assert r.pregunta.mensaje == ("Se detectó marca a las 17:43 como 'Entrada'. "
                                      "¿Es tu Salida de hoy o un turno de tarde?")
        assert r.pregunta.etiqueta_boton == "⇄ Mover a Salida"
        # Botón de 1 clic
        r2 = resolver_dia([marca("17:43:15", "Entrada", "BBB222")],
                          overrides=overrides_mover_a_salida("BBB222"))
        assert r2.salida == "17:43:15" and r2.pregunta is None
        assert r2.asignacion("BBB222").metodo == M_MANUAL

    def test_tres_marcas_intermedia(self):
        r = resolver_dia([marca("07:00:00"), marca("12:00:00", "Salida"), marca("16:00:00")])
        assert (r.ingreso, r.salida) == ("07:00:00", "16:00:00")
        assert r.asignacion("H120000").rol == INTERMEDIA
        assert AV_MARCAS_INTERMEDIAS in r.avisos

    def test_invertir_entrada_salida_manual(self):
        marcas = [marca("07:00:10", checksum="AAA111"), marca("17:43:15", checksum="BBB222")]
        r = resolver_dia(marcas)
        r2 = resolver_dia(marcas, overrides=overrides_invertir(r))
        assert (r2.ingreso_checksum, r2.salida_checksum) == ("BBB222", "AAA111")
        assert r2.asignacion("AAA111").badge == "Ajuste manual"

    def test_agrupar_por_fecha(self):
        g = agrupar_por_fecha([marca("07:00:00", fecha="2026-11-05"), marca("07:00:00", fecha="2026-11-06")])
        assert sorted(g) == ["2026-11-05", "2026-11-06"]


# =============================================================================== Conciliación con alerta
class TestConciliacionAlerta:
    def test_alerta_reconstruye_17_43_y_valida_jornada(self):
        r = resolver_dia([marca("06:55:02", "Entrada", "CCC333"), marca("17:43:15", "Entrada", "BBB222")],
                         alerta=alerta_106())
        c = r.conciliacion
        assert c.salida_reconstruida == "17:43:00"
        assert c.salida_confirmada is True
        assert c.jornada_validada is True
        assert c.badge == "Workera: Turno 07:00-16:00 | +103 min sobretiempo"
        b = r.asignacion("BBB222")
        assert b.rol == SALIDA and b.metodo == M_ALERTA and b.confirmada_por_alerta
        assert b.badge == "Salida confirmada por Workera (reloj marcó Entrada)"
        assert r.sugerencias == []
        # La jornada validada alimenta el calculador: 06:55:02 → 17:43:15 − 60 min colación.
        dc = calc_dia(Day(fecha=date(2026, 11, 6), ingreso=r.ingreso, salida=r.salida), Config())
        assert fmt_duracion(dc.trabajadas_s, True) == "9:48:13"
        assert fmt_duracion(dc.he_s, True) == "1:48:13"

    def test_alerta_confirma_marca_unica_entrada_como_salida(self):
        r = resolver_dia([marca("17:43:15", "Entrada", "BBB222")], alerta=alerta_106())
        assert r.pregunta is None                      # la alerta da 100 % de certeza
        assert r.salida == "17:43:15"
        assert r.asignacion("BBB222").badge == "Salida confirmada por Workera (reloj marcó Entrada)"
        s = r.sugerencia(INGRESO)
        assert s.hora == "07:00:00"                    # autocompletar con turno_inicio
        assert r.campos_dia(aplicar_sugerencias=True) == {"ingreso": "07:00:00", "salida": "17:43:15"}
        assert r.conciliacion.jornada_validada is False   # falta ingreso real

    def test_alerta_autocompleta_salida_faltante(self):
        r = resolver_dia([marca("06:58:00", "Entrada", "CCC333")], alerta=alerta_106())
        assert r.salida is None
        assert r.sugerencia(SALIDA).hora == "17:43:00"
        assert r.campos_dia() == {"ingreso": "06:58:00", "salida": None}       # no se aplica sola
        assert r.campos_dia(True)["salida"] == "17:43:00"

    def test_alerta_sin_marcas_reconstruye_dia_completo(self):
        r = resolver_dia([], alerta=alerta_106(), fecha="2026-11-06")
        assert r.campos_dia(True) == {"ingreso": "07:00:00", "salida": "17:43:00"}

    def test_alerta_atraso_confirma_ingreso(self):
        a = alerta_106(items=(ITEM_ATRASO.format(12),))
        r = resolver_dia([marca("07:12:40", "Salida", "ING1"), marca("16:05:00", "Salida", "SAL1")], alerta=a)
        assert r.conciliacion.ingreso_reconstruido == "07:12:00"
        assert r.asignacion("ING1").confirmada_por_alerta
        assert r.asignacion("ING1").badge == "Entrada confirmada por Workera (reloj marcó Salida)"

    def test_alerta_salida_anticipada(self):
        a = alerta_106(items=(ITEM_SALIDA_ANTICIPADA.format(30),))
        r = resolver_dia([marca("07:00:00", checksum="I"), marca("15:30:20", checksum="S")], alerta=a)
        assert r.conciliacion.salida_reconstruida == "15:30:00" and r.conciliacion.jornada_validada

    def test_alerta_que_no_calza_no_valida(self):
        r = resolver_dia([marca("07:00:00", checksum="I"), marca("16:10:00", checksum="S")], alerta=alerta_106())
        assert r.conciliacion.salida_confirmada is False
        assert r.conciliacion.jornada_validada is False
        assert "no_cuadra_con_alerta" in r.avisos

    def test_alerta_de_otra_fecha_se_ignora(self):
        a = parse_alerta_html(html_alerta(fecha="05/11/2026", dia="jueves"))
        r = resolver_dia([marca("07:00:00")], alerta=a)
        assert r.conciliacion is None


# =============================================================================== Correo real (captura 05/11/2026)
def test_alerta_real_desde_info_workera_salida_anticipada():
    """Las alertas llegan desde info@workera.com (no notificaciones@): deben aceptarse."""
    html = html_alerta(fecha="05/11/2026", dia="jueves", hora_alerta="20:02:31",
                       items=(ITEM_SALIDA_ANTICIPADA.format(33),))
    c = parse_email(email_bytes(html, "Alertas de asistencia automáticas - jueves 05/11/2026",
                                remitente="Workera.com <info@workera.com>"))
    assert c.tipo == TIPO_B and c.remitente_valido is True
    a = c.datos
    assert (a.fecha, a.turno_inicio, a.turno_fin) == ("2026-11-05", "07:00", "16:00")
    assert a.minutos("salida_anticipada") == 33
    assert a.hora_alerta == "2026-11-05T20:02:31-03:00"
    # Sin correos de marcación, la alerta permite reconstruir el día: salida = 16:00 − 33 min.
    r = resolver_dia([], alerta=a, fecha="2026-11-05")
    assert r.conciliacion.salida_reconstruida == "15:27:00"
    assert r.campos_dia(True) == {"ingreso": "07:00:00", "salida": "15:27:00"}
    assert r.conciliacion.badge == "Workera: Turno 07:00-16:00 | -33 min salida anticipada"


def test_busqueda_imap_por_dominio():
    from services.imap_client import criterio_remitente
    assert criterio_remitente("notificaciones@workera.com") == "workera.com"
    assert criterio_remitente("") == "workera.com"



# ----------------------------------------------------------------------------- Tipo C: solicitud aceptada
def test_solicitud_aceptada_crea_marca():
    from services.workera_parser import TIPO_C, checksum_solicitud, parse_email
    from tests.fixtures.workera_html import email_bytes, html_solicitud
    c = parse_email(email_bytes(html_solicitud(), "Solicitud de marcación aceptada"))
    m = c.datos
    assert c.tipo == TIPO_C and c.remitente_valido
    assert (m.fecha, m.hora, m.tipo_marca_declarado, m.activa) == ("2026-11-10", "09:30:00", "Entrada", True)
    assert m.checksum == checksum_solicitud("2026-11-10", "09:30:00", "entrada")
    assert m.nombre_trabajador == "NOMBRE APELLIDO PRUEBA" and m.rut_trabajador == ""


def test_solicitud_sin_asunto_se_reconoce_por_contenido():
    from services.workera_parser import TIPO_C, parse_email
    from tests.fixtures.workera_html import email_bytes, html_solicitud
    c = parse_email(email_bytes(html_solicitud(tipo="Salida", fecha_hora="03/11/2026 18:05"), "Workera"))
    assert c.tipo == TIPO_C and c.datos.hora == "18:05:00" and c.datos.tipo_marca_declarado == "Salida"


def test_solicitud_rechazada_queda_inactiva():
    from services.workera_parser import parse_email
    from tests.fixtures.workera_html import email_bytes, html_solicitud
    c = parse_email(email_bytes(html_solicitud(estado="Rechazado"), "Solicitud de marcación rechazada"))
    assert c.datos.activa is False


def test_solicitud_que_no_crea_marca_se_ignora():
    from services.workera_parser import parse_email
    from tests.fixtures.workera_html import email_bytes, html_solicitud
    raw = email_bytes(html_solicitud(requerimiento="Eliminaci&oacute;n de marcaci&oacute;n"),
                      "Solicitud de marcación aceptada")
    assert parse_email(raw) is None
