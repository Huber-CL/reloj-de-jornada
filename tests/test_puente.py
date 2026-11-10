"""Cliente del Puente Google + sincronización a través de él (sin red: puente simulado)."""
from __future__ import annotations

import asyncio
import base64
import json
from datetime import date
from urllib.parse import parse_qs, urlparse

import pytest

from core.calculator import Config
from data.database import Database
from services.puente import PuenteConfig, PuenteError, PuenteGoogle
from services.push_notifier import PushConfig
from services.sync import SyncService
from tests.fixtures.workera_html import RUT_OTRO, RUT_PRUEBA, email_bytes, html_alerta, html_marcacion

URL = "https://script.google.com/macros/s/AKfycbPRUEBA123/exec"
CLAVE = "c" * 40  # security-scan: ignore (clave ficticia del test)
VIE = date(2026, 11, 6)


def b64url(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).decode().rstrip("=")


class PuenteFalso:
    """Imita doGet/doPost de tools/workera_gmail_bridge.gs."""

    def __init__(self, correos):
        self.correos = correos
        self.llamadas = []
        self.props = {}

    async def __call__(self, metodo, url, cuerpo):
        q = {k: v[0] for k, v in parse_qs(urlparse(url).query).items()}
        self.llamadas.append((metodo, q, cuerpo))
        if q.get("token") != CLAVE:
            return 200, json.dumps({"ok": False, "error": "Clave inválida"})
        acc = q.get("accion")
        if acc == "ping":
            return 200, json.dumps({"ok": True, "version": "1.0"})
        if acc == "correos":
            return 200, json.dumps({"ok": True, "correos": [
                {"id": i, "fecha": 0, "raw": b64url(raw)} for i, raw in self.correos]})
        if acc == "respaldo_subir":
            self.props["respaldo"] = cuerpo
            return 200, json.dumps({"ok": True, "fecha": "2026-11-10T12:00:00Z"})
        if acc == "respaldo_bajar":
            return 200, json.dumps({"ok": True, "datos": self.props.get("respaldo"), "fecha": "2026-11-10T12:00:00Z"})
        if acc in ("config", "salida"):
            self.props[acc] = q
            return 200, json.dumps({"ok": True})
        return 200, json.dumps({"ok": False, "error": "Acción desconocida"})


A = "Notificación: Nuevos registros de asistencia"
CORREOS = [
    ("m1", email_bytes(html_marcacion(fecha="06/11/2026", hora="07:00:10", hash_="AAA111"), A)),
    ("m2", email_bytes(html_marcacion(fecha="06/11/2026", hora="17:43:15", hash_="BBB222"), A)),
    ("m3", email_bytes(html_marcacion(fecha="06/11/2026", hora="08:00:00", hash_="ZZZ999", rut=RUT_OTRO), A)),
    ("m4", email_bytes(html_alerta(), "Alertas de asistencia automáticas - viernes 06/11/2026",
                       remitente="Workera.com <info@workera.com>")),
]


def puente(falso):
    return PuenteGoogle(PuenteConfig(url=URL, clave=CLAVE, rut=RUT_PRUEBA), http=falso)


def test_config_valida_url_y_clave():
    assert PuenteConfig(url=URL, clave=CLAVE).listo
    assert not PuenteConfig(url="https://evil.example.com/exec", clave=CLAVE).listo
    assert len(PuenteConfig(url="x", clave="corta").errores()) == 2
    assert CLAVE not in repr(PuenteConfig(url=URL, clave=CLAVE))


def test_clave_incorrecta_da_error_claro():
    p = PuenteGoogle(PuenteConfig(url=URL, clave="d" * 40), http=PuenteFalso([]))
    with pytest.raises(PuenteError, match="Clave inválida"):
        asyncio.run(p.ping())


def test_sync_por_puente_resuelve_igual_que_imap(tmp_path):
    db = Database(tmp_path / "p.sqlite3")
    falso = PuenteFalso(CORREOS)
    sync = SyncService(db)
    r = asyncio.run(sync.sincronizar_puente(puente(falso), RUT_PRUEBA, hoy=date(2026, 11, 10)))
    assert (r.marcas_nuevas, r.alertas, r.ignorados_otro_rut) == (2, 1, 1)
    dia = db.get_day(VIE)
    assert (dia.ingreso, dia.salida) == ("07:00:10", "17:43:15")      # doble Entrada resuelta + alerta
    assert db.get_meta("ultima_sync_puente_fecha") == "2026-11-10"
    # pide solo desde la última sincronización (menos 3 días de solape)
    r2 = asyncio.run(sync.sincronizar_puente(puente(falso), RUT_PRUEBA, hoy=date(2026, 11, 10)))
    assert r2.correos_leidos == 0
    assert "desde" in falso.llamadas[-1][1]


def test_detectar_rut_por_puente(tmp_path):
    sync = SyncService(Database(tmp_path / "d.sqlite3"))
    ruts = asyncio.run(sync.detectar_ruts_puente(puente(PuenteFalso(CORREOS))))
    assert ruts.most_common(1)[0] == (RUT_PRUEBA, 3)


def test_respaldo_comprimido_ida_y_vuelta(tmp_path):
    db = Database(tmp_path / "r.sqlite3")
    db.set_meta("prueba", "hola")
    falso = PuenteFalso([])
    p = puente(falso)
    asyncio.run(p.subir_respaldo(db.exportar()))
    assert falso.llamadas[-1][0] == "POST" and len(falso.props["respaldo"]) < len(db.exportar())
    datos, fecha = asyncio.run(p.bajar_respaldo())
    copia = Database(":memory:")
    copia.importar(datos)
    assert copia.get_meta("prueba") == "hola" and fecha


def test_config_de_aviso_y_salida_informada():
    falso = PuenteFalso([])
    p = puente(falso)
    asyncio.run(p.configurar(PushConfig(activo=True, canal="reloj-abc123"), Config(aviso_salida_min=7)))
    cfg = falso.props["config"]
    assert (cfg["activo"], cfg["canal"], cfg["aviso_min"], cfg["dias"]) == ("1", "reloj-abc123", "7", "0,1,2,3,4")
    asyncio.run(p.informar_salida(VIE, 61200))
    assert falso.props["salida"]["salida_s"] == "61200"


# =============================================================================== respaldo entre dispositivos
@pytest.mark.parametrize("propio, remoto, dias, esperado", [
    (None, None, 10, "subir"),                                              # primer respaldo
    ("2026-11-10T12:00:00.000Z", "2026-11-10T12:00:00.000Z", 10, "subir"),  # el remoto es el mío
    ("2026-11-10T12:00:00.000Z", "2026-11-10T15:00:00.000Z", 10, "conflicto"),  # otro dispositivo subió después
    (None, "2026-11-10T15:00:00.000Z", 10, "conflicto"),                    # dispositivo nuevo con respaldo ajeno
    ("2026-11-10T12:00:00.000Z", None, 0, "omitir"),                        # base vacía: nunca pisar
])
def test_decidir_respaldo_auto(propio, remoto, dias, esperado):
    from services.puente import decidir_respaldo_auto
    assert decidir_respaldo_auto(propio, remoto, dias) == esperado


def test_contar_dias(tmp_path):
    from core.calculator import Day
    db = Database(tmp_path / "c.sqlite3")
    assert db.contar_dias() == 0
    db.save_day(Day(fecha=VIE, ingreso="07:00:00"))
    assert db.contar_dias() == 1
