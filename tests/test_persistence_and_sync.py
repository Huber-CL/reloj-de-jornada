"""SQLite + credenciales + sincronización Workera + casos de uso de la app."""
from __future__ import annotations

import asyncio
from datetime import date

import pytest

from core.calculator import H, Config, Day
from data.database import Database
from services.auth import CredentialStore, Credenciales, MemoryBackend
from services.jornada_service import JornadaService
from services.sync import SyncService
from tests.fixtures.workera_html import RUT_OTRO, RUT_PRUEBA, email_bytes, html_alerta, html_marcacion

VIE = date(2026, 11, 6)
ASUNTO_A = "Notificación: Nuevos registros de asistencia - 06/11/2026"
ASUNTO_B = "Alertas de asistencia automáticas - viernes 06/11/2026"
CLAVE_FICTICIA = "abcdefghijklmnop"  # security-scan: ignore (valor de prueba)


def correo_a(hora, hash_, rut=RUT_PRUEBA, fecha="06/11/2026"):
    return email_bytes(html_marcacion(fecha=fecha, hora=hora, hash_=hash_, rut=rut), ASUNTO_A)


class FakeMailbox:
    """Simula WorkeraMailbox: devuelve los mensajes cargados que no estén vistos."""
    buzon: list[tuple[str, bytes]] = []

    def __init__(self, settings):
        self.settings = settings

    def descargar(self, desde=None, uids_vistos=()):
        vistos = set(uids_vistos)
        return [(u, m) for u, m in self.buzon if u not in vistos]


@pytest.fixture
def db(tmp_path):
    d = Database(tmp_path / "test.sqlite3")
    yield d
    d.close()


@pytest.fixture
def cred():
    return Credenciales(usuario="usuario@example.com", app_password=CLAVE_FICTICIA, rut=RUT_PRUEBA)


@pytest.fixture
def svc(db):
    FakeMailbox.buzon = [
        ("1", correo_a("07:00:10", "AAA111")),
        ("2", correo_a("17:43:15", "BBB222")),                 # doble "Entrada"
        ("3", correo_a("08:00:00", "ZZZ999", rut=RUT_OTRO)),   # correo de otro trabajador
        ("4", email_bytes(html_alerta(), ASUNTO_B)),
        ("5", email_bytes("<p>Hola</p>", "Otra cosa")),
    ]
    return JornadaService(db, SyncService(db, mailbox_factory=FakeMailbox))


# =============================================================================== base de datos
class TestDatabase:
    def test_dia_y_config(self, db):
        db.save_day(Day(fecha=VIE, ingreso="07:00:00", extras=[{"inicio": "18:00", "fin": "20:00", "ref": "SVR"}]))
        d = db.get_day("2026-11-06")
        assert d.ingreso == "07:00:00" and d.extras[0]["ref"] == "SVR"
        assert db.get_day(date(2026, 11, 5)).ingreso is None
        db.save_config(Config(sueldo_base=1_500_000, dias_laborales=(0, 1, 2, 3)))
        assert db.get_config().sueldo_base == 1_500_000 and db.get_config().dias_laborales == (0, 1, 2, 3)

    def test_borrar_periodo(self, db):
        for d in (5, 6, 9):
            db.save_day(Day(fecha=date(2026, 11, d), ingreso="08:00:00"))
        assert db.borrar_periodo("2026-11-05", "2026-11-06") == 2
        assert list(db.days_between("2026-11-01", "2026-11-30")) == [date(2026, 11, 9)]


# =============================================================================== credenciales
class TestCredenciales:
    def test_guardar_y_cargar(self):
        store = CredentialStore(MemoryBackend())
        c = Credenciales(usuario=" Amigo@Example.com ", app_password="abcd efgh ijkl mnop",  # security-scan: ignore
                         rut="123456785", nombre="Amigo")
        asyncio.run(store.guardar(c))
        cargada = asyncio.run(store.cargar())
        assert cargada.usuario == "amigo@example.com" and cargada.app_password == CLAVE_FICTICIA
        assert cargada.rut == "12.345.678-5" and cargada.carpeta == "02_Reloj_Control"
        assert CLAVE_FICTICIA not in repr(cargada)
        asyncio.run(store.borrar())
        assert not asyncio.run(store.cargar()).completas

    def test_validacion(self):
        e = Credenciales(usuario="malo", app_password="corta", rut="12.345.678-6").errores()
        assert len(e) == 3


# =============================================================================== sincronización
class TestSync:
    def test_sincroniza_solo_mi_rut_y_resuelve(self, svc, db, cred):
        r = svc.sync.sincronizar(cred, hoy=date(2026, 11, 9))
        assert (r.marcas_nuevas, r.alertas, r.ignorados_otro_rut, r.errores) == (2, 1, 1, [])
        dia = db.get_day(VIE)
        assert (dia.ingreso, dia.salida) == ("07:00:10", "17:43:15")
        assert dia.fuente == {"ingreso": "workera", "salida": "workera"}
        ev = {e["checksum"]: e for e in db.eventos(VIE)}
        assert ev["BBB222"]["rol_asignado"] == "salida" and ev["BBB222"]["metodo_asignacion"] == "alerta"
        assert "ZZZ999" not in ev
        # Segunda sincronización: nada nuevo (UIDs vistos + checksum idempotente).
        r2 = svc.sync.sincronizar(cred, hoy=date(2026, 11, 9))
        assert r2.correos_leidos == 0

    def test_sin_rut_no_importa_y_detecta(self, svc, db, cred):
        cred.rut = ""
        r = svc.sync.sincronizar(cred)
        assert r.marcas_nuevas == 0 and r.pendientes_sin_rut == 4
        assert r.ruts_encontrados.most_common(1)[0] == ("12.345.678-5", 3)
        assert db.uids_vistos(cred.usuario, cred.carpeta) == {"5"}   # los de Workera se reintentarán
        assert svc.sync.detectar_ruts(cred)["20.000.003-K"] == 1

    def test_no_pisa_lo_editado_a_mano(self, svc, db, cred):
        svc.guardar_dia_editado(Day(fecha=VIE, ingreso="06:30:00"))
        svc.sync.sincronizar(cred)
        dia = db.get_day(VIE)
        assert dia.ingreso == "06:30:00" and dia.fuente["ingreso"] == "manual"
        assert dia.salida == "17:43:15"

    def test_workera_reemplaza_marca_de_la_app(self, svc, db, cred):
        svc.marcar_ingreso(VIE, 7 * H)
        svc.sync.sincronizar(cred)
        assert db.get_day(VIE).ingreso == "07:00:10"

    def test_invertir_y_deshacer(self, svc, db, cred):
        svc.sync.sincronizar(cred)
        svc.invertir(VIE)
        dia = db.get_day(VIE)
        assert (dia.ingreso, dia.salida) == ("17:43:15", "07:00:10")
        svc.deshacer_ajustes_workera(VIE)
        assert db.get_day(VIE).ingreso == "07:00:10"

    def test_sugerencia_de_alerta_se_mantiene(self, svc, db, cred):
        FakeMailbox.buzon = [("1", correo_a("06:58:00", "CCC333")), ("4", email_bytes(html_alerta(), ASUNTO_B))]
        svc.sync.sincronizar(cred)
        assert db.get_day(VIE).salida is None
        svc.aplicar_sugerencia(VIE, "salida")
        svc.resolucion(VIE)                                    # re-reconciliar no la borra
        dia = db.get_day(VIE)
        assert dia.salida == "17:43:00" and dia.fuente["salida"] == "alerta"

    def test_mover_a_salida(self, svc, db, cred):
        FakeMailbox.buzon = [("2", correo_a("17:43:15", "BBB222"))]
        svc.sync.sincronizar(cred)
        res = svc.resolucion(VIE)
        assert res.pregunta is not None
        svc.mover_a_salida(VIE, "BBB222")
        assert db.get_day(VIE).salida == "17:43:15"


# =============================================================================== casos de uso
class TestJornadaService:
    def test_estado_en_curso(self, svc):
        lunes = date(2026, 11, 9)
        svc.marcar_ingreso(lunes, 8 * H)
        st = svc.estado(lunes, ahora_s=12 * H + 30 * 60)
        assert st.salida_estimada_s == 17 * H and st.aviso_salida_s == 17 * H - 300
        assert st.transcurrido_s == 4.5 * H and st.restante_s == 4.5 * H
        assert st.progreso == pytest.approx(0.5)
        assert {o.codigo for o in st.opciones} >= {"normal", "comp", "adel", "he1", "he2"}

    def test_plan_y_salida_con_he(self, svc):
        lunes = date(2026, 11, 9)
        svc.marcar_ingreso(lunes, 8 * H)
        svc.elegir_plan(lunes, "he1")
        assert svc.estado(lunes, 9 * H).salida_estimada_s == 18 * H
        c = svc.marcar_salida(lunes, 18 * H)
        assert c.he_s == H
        assert svc.guardar_motivo(lunes, "Paciente tardío").motivoHE == "Paciente tardío"

    def test_cambio_de_dia(self, svc):
        sab = date(2026, 11, 7)
        assert VIE in svc.candidatos_cambio(sab)
        svc.cambio_de_dia(sab, VIE)
        assert svc.dia(VIE).tipo == "cambio"
        svc.deshacer_cambio(sab)
        assert svc.dia(VIE).tipo is None and svc.dia(sab).cambioDe is None


# =============================================================================== vacaciones / licencias en rango
class TestMarcarRango:
    def test_marca_solo_laborales_y_respeta_marcas(self, svc, db):
        # lun 9 → dom 22 nov; el miércoles 11 ya tiene marcas
        svc.marcar_ingreso(date(2026, 11, 11), 8 * H)
        r = svc.marcar_rango(date(2026, 11, 9), date(2026, 11, 22), "vacaciones")
        assert len(r["marcados"]) == 9                          # 10 laborales − 1 con marcas
        assert r["con_marcas"] == [date(2026, 11, 11)]
        assert svc.dia(date(2026, 11, 13)).tipo == "vacaciones"
        assert svc.dia(date(2026, 11, 14)).tipo is None         # sábado intacto
        assert svc.dia(date(2026, 11, 11)).tipo is None
        # la semana de vacaciones completas (16–22) tiene meta 0
        assert svc.resumen_semana(date(2026, 11, 18)).meta_s == 0

    def test_quitar_marca(self, svc):
        svc.marcar_rango(date(2026, 11, 16), date(2026, 11, 20), "licencia")
        r = svc.marcar_rango(date(2026, 11, 16), date(2026, 11, 20), None)
        assert len(r["marcados"]) == 5
        assert svc.dia(date(2026, 11, 17)).tipo is None

    def test_validaciones(self, svc):
        with pytest.raises(ValueError):
            svc.marcar_rango(date(2026, 11, 20), date(2026, 11, 16), "vacaciones")
        with pytest.raises(ValueError):
            svc.marcar_rango(date(2026, 1, 1), date(2026, 12, 31), "vacaciones")
        with pytest.raises(ValueError):
            svc.marcar_rango(date(2026, 11, 16), date(2026, 11, 20), "fiesta")


class TestVacacionesServicio:
    def test_no_descuenta_feriados_marcados(self, svc):
        svc.marcar_rango(date(2026, 12, 8), date(2026, 12, 8), "feriado")
        assert svc.contar_habiles(date(2026, 12, 7), date(2026, 12, 11)) == 4
        r = svc.marcar_rango(date(2026, 12, 7), date(2026, 12, 11), "vacaciones")
        assert len(r["marcados"]) == 4 and r["feriados"] == [date(2026, 12, 8)]
        assert svc.dia(date(2026, 12, 8)).tipo == "feriado"

    def test_saldo_y_guardado(self, svc):
        svc.guardar_saldo_vacaciones(20, date(2026, 11, 1))
        svc.marcar_rango(date(2026, 11, 16), date(2026, 11, 20), "vacaciones")
        s = svc.saldo_vacaciones(hoy=date(2026, 11, 11))
        assert s.configurado and s.programados == 5 and s.disponibles == 15
        with pytest.raises(ValueError):
            svc.guardar_saldo_vacaciones(-1, date(2026, 11, 1))



class TestSolicitudAceptada:
    def test_completa_el_dia_y_no_duplica(self, db):
        from tests.fixtures.workera_html import html_solicitud
        sync = SyncService(db)
        cred = Credenciales(usuario="yo@example.com", carpeta="INBOX", rut=RUT_PRUEBA)
        salida = correo_a("18:10:00", "AAA111", fecha="10/11/2026")
        solicitud = email_bytes(html_solicitud(), "Solicitud de marcación aceptada")
        r = sync.procesar([("1", salida), ("2", solicitud), ("3", solicitud)], cred)
        assert r.marcas_nuevas == 2
        d = db.get_day(date(2026, 11, 10))
        assert (d.ingreso, d.salida) == ("09:30:00", "18:10:00")

    def test_relee_una_vez_al_actualizar_el_lector(self, db):
        from services.sync import VERSION_LECTOR
        db.marcar_uid_visto("yo@gmail.com", "INBOX", "viejo")
        db.set_meta("ultima_sync_fecha", "2026-11-10")
        FakeMailbox.buzon = []
        sync = SyncService(db, mailbox_factory=FakeMailbox)
        cred = Credenciales(usuario="yo@gmail.com", app_password=CLAVE_FICTICIA, carpeta="INBOX", rut=RUT_PRUEBA)
        sync.sincronizar(cred, hoy=date(2026, 11, 12))
        assert db.get_meta("version_lector") == VERSION_LECTOR
        assert "viejo" not in db.uids_vistos("yo@gmail.com", "INBOX")
        db.marcar_uid_visto("yo@gmail.com", "INBOX", "nuevo")
        sync.sincronizar(cred, hoy=date(2026, 11, 12))          # la segunda vez ya no olvida
        assert "nuevo" in db.uids_vistos("yo@gmail.com", "INBOX")
