"""Reglas de cálculo de reloj-de-jornada.md."""
from __future__ import annotations

from datetime import date

import pytest

from core.calculator import (
    H, Config, Day, aplicar_cambio_dia, aviso_cierre_semana, aviso_deuda, aviso_ultimo_dia,
    calc_dia, calc_periodo, deshacer_cambio_dia, es_penultimo_laboral, es_ultimo_laboral,
    fmt_hms, hora_limite_s, opciones_plan, parse_hms, rango_periodo, salida_plan_s, valor_hora_extra,
)

LUN, MAR, MIE, JUE, VIE, SAB = (date(2026, 11, d) for d in (2, 3, 4, 5, 6, 7))
CFG = Config()


def dia(f, ing=None, sal=None, **kw):
    return Day(fecha=f, ingreso=ing, salida=sal, **kw)


def semana(*days):
    return {d.fecha: d for d in days}


def opcion(ops, codigo, antes=0):
    return next(o for o in ops if o.codigo == codigo and o.antes_s == antes)


class TestDia:
    def test_hms(self):
        assert parse_hms("07:00") == 7 * H and fmt_hms(parse_hms("17:43:15")) == "17:43:15"
        with pytest.raises(ValueError):
            parse_hms("25:00")

    def test_jornada_normal(self):
        c = calc_dia(dia(LUN, "08:00:00", "17:00:00"), CFG)
        assert c.salida_normal_s == 17 * H
        assert (c.trabajadas_s, c.he_s, c.faltante_s, c.saldo_s) == (8 * H, 0, 0, 0)

    def test_he_con_maximo_diario(self):
        c = calc_dia(dia(LUN, "08:00:00", "20:00:00"), CFG)
        assert c.he_bruta_s == 3 * H and c.he_s == 2 * H and c.he_excedente_s == H

    def test_faltante(self):
        c = calc_dia(dia(LUN, "08:00:00", "15:30:00"), CFG)
        assert c.faltante_s == int(1.5 * H) and c.saldo_s == -int(1.5 * H)

    def test_dia_no_laboral_todo_es_he_sin_colacion(self):
        c = calc_dia(dia(SAB, "09:00:00", "13:00:00"), CFG)
        assert c.meta_s == 0 and c.colacion_s == 0 and c.he_s == 4 * H

    @pytest.mark.parametrize("tipo", ["feriado", "vacaciones", "licencia", "permiso"])
    def test_tipos_no_laborales(self, tipo):
        assert calc_dia(dia(LUN, "09:00:00", "10:00:00", tipo=tipo), CFG).he_s == H

    def test_estados_incompletos_no_generan_faltante(self):
        assert calc_dia(dia(LUN), CFG).estado == "sin_registro"
        assert calc_dia(dia(LUN, "08:00:00"), CFG).estado == "en_curso"
        assert calc_dia(dia(LUN, None, "17:00:00"), CFG).saldo_s == 0

    def test_extras_no_afectan_saldo(self):
        c = calc_dia(dia(LUN, "08:00:00", "17:00:00", extras=[{"inicio": "18:00", "fin": "21:00", "ref": "SVR"}]), CFG)
        assert c.extras_s == 3 * H and c.saldo_s == 0

    def test_cruce_medianoche(self):
        assert calc_dia(dia(SAB, "22:00:00", "02:00:00"), CFG).trabajadas_s == 4 * H

    def test_objetivo_y_colacion_propios(self):
        c = calc_dia(dia(LUN, "08:00:00", "14:30:00", objetivoH=6, colacionMin=30), CFG)
        assert c.saldo_s == 0


class TestPlanes:
    def test_opciones_basicas(self):
        hoy = dia(MIE, "08:00:00")
        ops = opciones_plan(hoy, semana(hoy), CFG)
        assert opcion(ops, "normal").salida_s == 17 * H
        assert opcion(ops, "he1").salida_s == 18 * H and opcion(ops, "he2").salida_s == 19 * H
        assert opcion(ops, "adel", 1800).salida_s == int(16.5 * H)
        assert not any(o.codigo == "tope" for o in ops)

    def test_compensar_usa_saldo_a_favor_con_maximo(self):
        dias = semana(dia(LUN, "08:00:00", "19:00:00"), dia(MAR, "08:00:00", "19:00:00"), dia(MIE, "08:00:00"))
        comp = opcion(opciones_plan(dias[MIE], dias, CFG), "comp")
        assert comp.delta_s == -2 * H and comp.salida_s == 15 * H      # 4 h a favor, máx 2 h/día

    def test_compensar_deuda_recomendado(self):
        dias = semana(dia(LUN, "08:00:00", "16:00:00"), dia(MAR, "08:00:00"))
        comp = opcion(opciones_plan(dias[MAR], dias, CFG), "comp")
        assert comp.recomendada and comp.salida_s == 18 * H
        assert aviso_deuda(dias[MAR], dias, CFG) == {"deuda_s": H, "sugerido_hoy_s": H, "plan_recomendado": "comp"}

    def test_salir_antes_usa_a_favor_y_deja_deuda(self):
        dias = semana(dia(LUN, "08:00:00", "17:30:00"), dia(MAR, "08:00:00"))
        op = opcion(opciones_plan(dias[MAR], dias, CFG), "adel", 3600)
        assert "Usa 0:30 a favor, queda deuda 0:30" == op.nota

    def test_tope_deshabilita_y_ofrece_hasta_el_tope(self):
        # 9 h 30 de saldo previo → solo quedan 30 min hasta el tope de 10 h.
        cfg = Config(max_he_dia_h=5)
        dias = semana(dia(LUN, "08:00:00", "21:30:00"), dia(MAR, "08:00:00", "22:00:00"), dia(MIE, "08:00:00"))
        ops = opciones_plan(dias[MIE], dias, cfg)
        assert not opcion(ops, "he1").habilitada and not opcion(ops, "he2").habilitada
        tope = opcion(ops, "tope")
        assert tope.salida_s == int(17.5 * H)
        assert hora_limite_s(dias[MIE], dias, cfg) == int(17.5 * H)
        dias[MIE].plan = "tope"
        assert salida_plan_s(dias[MIE], dias, cfg) == int(17.5 * H)

    def test_dia_no_laboral_sin_planes(self):
        hoy = dia(SAB, "09:00:00")
        assert opciones_plan(hoy, semana(hoy), CFG) == []


class TestSemanaYAvisos:
    def test_penultimo_y_ultimo_con_feriado(self):
        dias = semana(dia(VIE, tipo="feriado"))
        assert es_penultimo_laboral(MIE, dias, CFG) and es_ultimo_laboral(JUE, dias, CFG)

    def test_cambio_de_dia(self):
        sab, vie = aplicar_cambio_dia(dia(SAB, "08:00:00", "17:00:00"), dia(VIE))
        dias = semana(sab, vie)
        assert calc_dia(sab, CFG).meta_s == 8 * H and calc_dia(sab, CFG).saldo_s == 0
        assert vie.tipo == "cambio" and vie.cambioCon == "2026-11-07" and sab.cambioDe == "2026-11-06"
        assert es_ultimo_laboral(SAB, dias, CFG) and es_penultimo_laboral(JUE, dias, CFG)
        sab2, vie2 = deshacer_cambio_dia(sab, vie)
        assert sab2.cambioDe is None and vie2.tipo is None
        with pytest.raises(ValueError):
            aplicar_cambio_dia(dia(SAB), dia(date(2026, 11, 13)))

    def test_aviso_cierre_semana(self):
        dias = semana(dia(LUN, "08:00:00", "18:00:00"), dia(JUE, "08:00:00"))
        assert aviso_cierre_semana(dias[JUE], dias, CFG, ahora_s=13 * H) is None
        av = aviso_cierre_semana(dias[JUE], dias, CFG, ahora_s=14 * H)
        assert av["saldo_proyectado_s"] == H and av["manana"] == VIE and av["compensar_manana_s"] == H

    def test_aviso_ultimo_dia_cierra_en_cero(self):
        dias = semana(dia(LUN, "08:00:00", "18:30:00"), dia(VIE, "08:00:00"))
        av = aviso_ultimo_dia(dias[VIE], dias, CFG)
        assert fmt_hms(av["salida_s"]) == "15:30:00" and av["cierra_en_cero"]


class TestPeriodoYValor:
    def test_valor_he_ley_42h(self):
        assert valor_hora_extra(Config(sueldo_base=1_500_000)) == pytest.approx(12_500)
        assert valor_hora_extra(Config(valor_he_manual=9000)) == 9000

    @pytest.mark.parametrize("ref, esperado", [
        (date(2026, 11, 9), (date(2026, 10, 25), date(2026, 11, 24))),
        (date(2026, 11, 25), (date(2026, 11, 25), date(2026, 12, 24))),
        (date(2026, 12, 30), (date(2026, 12, 25), date(2027, 1, 24))),
    ])
    def test_ciclo_mensual(self, ref, esperado):
        assert rango_periodo("ciclo", ref, 25) == esperado

    def test_mes_y_fechas(self):
        assert rango_periodo("mes", date(2028, 2, 10)) == (date(2028, 2, 1), date(2028, 2, 29))
        assert rango_periodo("fechas", date(2026, 1, 1), desde="2026-09-25", hasta="2026-10-28") == (
            date(2026, 9, 25), date(2026, 10, 28))

    def test_periodo_con_tope_semanal_y_monto(self):
        cfg = Config(sueldo_base=1_500_000, max_he_dia_h=4, valor_hora_extraordinaria=10_000)
        dias = {}
        for f in (LUN, MAR, MIE):                       # 3 × 4 h HE = 12 h → tope 10 h
            dias[f] = dia(f, "08:00:00", "21:00:00")
        dias[JUE] = dia(JUE, "08:00:00", "17:00:00", extras=[{"inicio": "18:00", "fin": "20:00", "ref": "AAR"}])
        p = calc_periodo(dias, LUN, date(2026, 11, 8), cfg, hoy=date(2026, 11, 9))
        assert p.he_s == 12 * H and p.saldo_neto_s == 10 * H
        assert p.dias_trabajados == 4 and p.sin_registro == [VIE]
        assert p.monto_he == 125_000 and p.monto_extras == 20_000 and p.monto_total == 145_000

    def test_saldo_negativo_paga_cero(self):
        dias = {LUN: dia(LUN, "08:00:00", "15:00:00")}
        p = calc_periodo(dias, LUN, LUN, Config(sueldo_base=1_500_000))
        assert p.saldo_neto_s == -2 * H and p.monto_he == 0


class TestResumenSemana:
    L, MA, MI, J, V = (date(2026, 11, d) for d in (9, 10, 11, 12, 13))

    def test_rango_semana(self):
        assert rango_periodo("semana", date(2026, 11, 11)) == (date(2026, 11, 9), date(2026, 11, 15))
        assert Config().periodo_modo == "semana"

    def test_llevas_faltan_y_por_dia_con_dia_en_curso(self):
        from core.calculator import resumen_semana
        dias = semana(dia(self.L, "08:00:00", "17:00:00"), dia(self.MA, "08:00:00", "16:00:00"),
                      dia(self.MI, "08:00:00"))
        r = resumen_semana(self.MI, dias, CFG, hoy=self.MI, ahora_s=12 * H)
        assert r.meta_s == 40 * H and r.dias_laborales == 5
        assert r.llevas_s == 18 * H                     # 8 + 7 + 3 (hoy: 4 h − colación)
        assert r.faltan_s == 22 * H and r.exceso_s == 0
        assert r.dias_restantes == 3                    # hoy (en curso), jueves y viernes
        assert r.por_dia_s == 22 * H // 3
        assert r.saldo_s == -H                          # solo días completos: lunes 0, martes −1 h

    def test_feriado_baja_la_meta_y_dia_sin_registro(self):
        from core.calculator import resumen_semana
        dias = semana(dia(self.MA, "08:00:00", "17:00:00"), dia(self.J, tipo="feriado"))
        r = resumen_semana(self.MI, dias, CFG, hoy=self.MI)
        assert r.meta_s == 32 * H and r.dias_laborales == 4
        assert r.sin_registro == [self.L]               # lunes laboral pasado sin marcas
        assert r.dias_restantes == 2                    # miércoles (sin marcar aún) y viernes

    def test_ultimo_dia_hora_para_completar_la_semana(self):
        from core.calculator import resumen_semana
        dias = semana(*(dia(f, "08:00:00", "17:00:00") for f in (self.L, self.MA, self.MI, self.J)),
                      dia(self.V, "08:00:00"))
        r = resumen_semana(self.V, dias, CFG, hoy=self.V, ahora_s=10 * H)
        assert r.llevas_s == 33 * H and r.faltan_s == 7 * H and r.dias_restantes == 1
        assert r.salida_hoy_s == 17 * H                 # 08:00 + 8 h + colación
