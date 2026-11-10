"""Avisos push por ntfy (sin red: transporte falso) y respaldo de la base para la PWA."""
from __future__ import annotations

import asyncio
from datetime import date

import pytest

from core.calculator import H, Day
from data.database import Database
from services.jornada_service import JornadaService
from services.push_notifier import PushConfig, PushError, PushNotifier, generar_canal, instante_local, seq_salida

HOY = date(2026, 11, 9)


class FakeHttp:
    def __init__(self, status=200):
        self.llamadas = []
        self.status = status

    async def __call__(self, metodo, url, headers, cuerpo):
        self.llamadas.append((metodo, url, headers, cuerpo.decode()))
        return self.status


def notifier(ahora_s: int, http: FakeHttp, canal="reloj-abc123"):
    cfg = PushConfig(activo=True, canal=canal)
    return PushNotifier(cfg, transporte=http, reloj=lambda: instante_local(HOY, ahora_s))


def test_canal_aleatorio():
    a, b = generar_canal(), generar_canal()
    assert a != b and a.startswith("reloj-") and len(a) == 30
    assert PushConfig(activo=True, canal=a).listo
    assert not PushConfig(activo=True, canal="con espacios").listo


def test_programa_aviso_5_min_antes_con_sequence_id():
    http = FakeHttp()
    cuando = asyncio.run(notifier(8 * H, http).programar_salida(HOY, 17 * H, 5))
    metodo, url, headers, cuerpo = http.llamadas[0]
    assert metodo == "POST" and url == "https://ntfy.sh/reloj-abc123/salida-20261109"
    assert headers["At"] == str(int(instante_local(HOY, 17 * H - 300))) == str(int(cuando))
    assert headers["Priority"] == "high"
    assert cuerpo == "Tu salida es a las 17:00 (en 5 min)."


def test_aviso_ya_pasado_cancela():
    http = FakeHttp()
    assert asyncio.run(notifier(17 * H, http).programar_salida(HOY, 17 * H, 5)) is None
    assert http.llamadas[0][:2] == ("DELETE", "https://ntfy.sh/reloj-abc123/salida-20261109")


def test_cancelar_tolera_404_y_falla_con_500():
    asyncio.run(notifier(8 * H, FakeHttp(404)).cancelar_salida(HOY))
    with pytest.raises(PushError):
        asyncio.run(notifier(8 * H, FakeHttp(500)).programar_salida(HOY, 17 * H, 5))


def test_canal_invalido_no_envia():
    http = FakeHttp()
    with pytest.raises(PushError):
        asyncio.run(notifier(8 * H, http, canal="../otro").prueba())
    assert http.llamadas == []


def test_objetivo_aviso_sigue_el_plan(tmp_path):
    db = Database(tmp_path / "x.sqlite3")
    svc = JornadaService(db)
    assert svc.objetivo_aviso(HOY) is None                     # sin ingreso
    svc.marcar_ingreso(HOY, 8 * H)
    assert svc.objetivo_aviso(HOY) == 17 * H
    svc.elegir_plan(HOY, "he1")
    assert svc.objetivo_aviso(HOY) == 18 * H                   # cambiar plan reprograma
    svc.marcar_salida(HOY, 18 * H)
    assert svc.objetivo_aviso(HOY) is None                     # ya salió → cancelar
    assert seq_salida(HOY) == "salida-20261109"


def test_respaldo_base_en_memoria_para_pwa():
    cambios = []
    db = Database(":memory:", al_cambiar=lambda: cambios.append(1))
    db.save_day(Day(fecha=HOY, ingreso="07:00:00"))
    assert cambios
    copia = Database(":memory:")
    copia.importar(db.exportar())
    assert copia.get_day(HOY).ingreso == "07:00:00"
