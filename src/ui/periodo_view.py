"""Pestaña Periodo: resumen, estimado a cobrar, tabla semanal, lista de días y borrado."""
from __future__ import annotations

import asyncio
from dataclasses import replace
from datetime import date, datetime, timedelta

import flet as ft

from core import calculator as calc
from ui import widgets as w
from ui.editor_dia import abrir_editor

MODOS = {"semana": "Semana (lun–dom)", "mes": "Mes calendario", "ciclo": "Ciclo mensual",
         "fechas": "Fechas específicas"}


def pesos(n: float) -> str:
    return "$" + f"{round(n):,}".replace(",", ".")


def num_dias(n: float) -> str:
    """15 → «15», 8.25 → «8,25»."""
    return str(int(n)) if float(n).is_integer() else f"{n:.2f}".rstrip("0").replace(".", ",")


def rango_corto(a: date, b: date) -> str:
    if a == b:
        return w.fecha_corta(a)
    if (a.year, a.month) == (b.year, b.month):
        return f"{a.day}–{b.day} {w.MESES_CORTOS[b.month - 1]}"
    return f"{a.day} {w.MESES_CORTOS[a.month - 1]} – {b.day} {w.MESES_CORTOS[b.month - 1]}"


def a_fecha(v):
    if isinstance(v, datetime):
        return (v.astimezone() if v.tzinfo else v).date()
    return v


class PeriodoView:
    def __init__(self, app):
        self.app = app
        self.page = app.page
        self.ref = date.today()
        self.lista = ft.ListView(padding=12, spacing=10, expand=True)
        self._confirmando_borrado = False

    def construir(self) -> ft.Control:
        return self.lista

    def refrescar(self) -> None:
        cfg = self.app.svc.cfg
        p = self.app.svc.periodo(self.ref)
        self.p = p
        titulo = f"{w.fecha_corta(p.desde)} – {w.fecha_corta(p.hasta)}"
        if cfg.periodo_modo == "mes":
            titulo = f"{w.MESES[p.desde.month - 1].capitalize()} {p.desde.year}"
        elif cfg.periodo_modo == "semana":
            titulo = (f"Semana {p.desde.day}–{p.hasta.day} {w.MESES_CORTOS[p.hasta.month - 1]}"
                      if p.desde.month == p.hasta.month else
                      f"Semana {p.desde.day} {w.MESES_CORTOS[p.desde.month - 1]} – "
                      f"{p.hasta.day} {w.MESES_CORTOS[p.hasta.month - 1]}")

        cab = ft.Row([
            ft.IconButton(ft.Icons.CHEVRON_LEFT, on_click=lambda _: self._mover(-1),
                          disabled=cfg.periodo_modo == "fechas"),
            ft.Container(ft.Column([
                ft.Text(titulo, size=20, weight=ft.FontWeight.BOLD),
                ft.Text(MODOS[cfg.periodo_modo] + " · toca para cambiar", size=12, color=ft.Colors.ON_SURFACE_VARIANT),
            ], spacing=0, horizontal_alignment=ft.CrossAxisAlignment.CENTER),
                expand=True, on_click=lambda _: self._dialogo_modo(), ink=True, border_radius=8),
            ft.IconButton(ft.Icons.CHEVRON_RIGHT, on_click=lambda _: self._mover(1),
                          disabled=cfg.periodo_modo == "fechas"),
        ])

        resumen = w.tarjeta(
            ft.Row([w.dato("Trabajadas", w.dur(p.trabajadas_s)), w.dato("Horas extra", w.dur(p.he_s), w.VERDE),
                    w.dato("Faltantes", w.dur(p.faltante_s), w.ROJO if p.faltante_s else None)],
                   alignment=ft.MainAxisAlignment.SPACE_BETWEEN, wrap=True),
            ft.Row([w.dato("Saldo neto", w.dur_signo(p.saldo_neto_s), grande=True,
                           color=w.VERDE if p.saldo_neto_s > 0 else w.ROJO if p.saldo_neto_s < 0 else None),
                    w.dato("Extraordinarias", w.dur(p.extras_s)), w.dato("Días trabajados", str(p.dias_trabajados))],
                   alignment=ft.MainAxisAlignment.SPACE_BETWEEN, wrap=True),
            titulo="Resumen", icono=ft.Icons.INSIGHTS,
        )

        if p.valor_he:
            base = "saldo neto" if cfg.pagar_saldo_neto else "horas extra"
            detalle = [ft.Text(f"Valor hora extra: {pesos(p.valor_he)} (sobre {base})", size=13)]
            if p.monto_extras:
                detalle.append(ft.Text(f"Jornadas extraordinarias: {pesos(p.monto_extras)}", size=13))
            cobro = w.tarjeta(ft.Text(pesos(p.monto_total), size=28, weight=ft.FontWeight.BOLD, color=w.VERDE),
                              *detalle, ft.Text("Monto bruto estimado, antes de descuentos legales.", size=11,
                                                color=ft.Colors.ON_SURFACE_VARIANT),
                              titulo="Estimado a cobrar", icono=ft.Icons.PAYMENTS)
        else:
            cobro = w.tarjeta(ft.Text("Ingresa tu sueldo base en Ajustes para estimar el monto.", size=13),
                              titulo="Estimado a cobrar", icono=ft.Icons.PAYMENTS)

        tabla = ft.DataTable(
            column_spacing=18, heading_row_height=36, data_row_min_height=32, data_row_max_height=40,
            columns=[ft.DataColumn(ft.Text("Semana")), ft.DataColumn(ft.Text("HE"), numeric=True),
                     ft.DataColumn(ft.Text("Falt."), numeric=True), ft.DataColumn(ft.Text("Saldo"), numeric=True)],
            rows=[ft.DataRow(cells=[
                ft.DataCell(ft.Text(f"{s.lunes.day}/{s.lunes.month}–{s.domingo.day}/{s.domingo.month}")),
                ft.DataCell(ft.Text(w.dur(s.he_s))), ft.DataCell(ft.Text(w.dur(s.faltante_s))),
                ft.DataCell(ft.Text(w.dur_signo(s.saldo_computable_s) + (" *" if s.saldo_s != s.saldo_computable_s else ""))),
            ]) for s in p.semanas] + [ft.DataRow(cells=[
                ft.DataCell(ft.Text("Total", weight=ft.FontWeight.BOLD)),
                ft.DataCell(ft.Text(w.dur(p.he_s), weight=ft.FontWeight.BOLD)),
                ft.DataCell(ft.Text(w.dur(p.faltante_s), weight=ft.FontWeight.BOLD)),
                ft.DataCell(ft.Text(w.dur_signo(p.saldo_neto_s), weight=ft.FontWeight.BOLD)),
            ])],
        )
        semanas = w.tarjeta(ft.Row([tabla], scroll=ft.ScrollMode.AUTO),
                            ft.Text("* recortado al tope de saldo", size=11, color=ft.Colors.ON_SURFACE_VARIANT),
                            titulo="Horas extra por semana", icono=ft.Icons.TABLE_CHART)

        dias = self.app.db.days_between(p.desde, p.hasta)
        filas = [self._fila_dia(c, dias.get(c.fecha)) for c in reversed(p.dias) if c.fecha <= date.today()]
        lista_dias = w.tarjeta(*filas or [ft.Text("Sin días en este periodo.")], titulo="Días", icono=ft.Icons.LIST)

        acciones = ft.Row([
            ft.OutlinedButton("Licencia / permiso / feriado", icon=ft.Icons.EVENT_BUSY,
                              on_click=lambda _: self._dialogo_ausencia("licencia")),
            ft.OutlinedButton("Registrar un día anterior", icon=ft.Icons.EDIT_CALENDAR, on_click=self._registrar_anterior),
            ft.TextButton("Toca otra vez para borrar" if self._confirmando_borrado else "Borrar datos del periodo",
                          icon=ft.Icons.DELETE_FOREVER, on_click=self._borrar,
                          style=ft.ButtonStyle(color=w.ROJO)),
        ], wrap=True)
        if cfg.periodo_modo == "semana":
            self.lista.controls = [cab, self._tarjeta_semana(), self._tarjeta_vacaciones(), cobro, acciones,
                                   lista_dias]
        else:
            self.lista.controls = [cab, resumen, cobro, semanas, self._tarjeta_vacaciones(), acciones, lista_dias]

    def _tarjeta_semana(self) -> ft.Control:
        r = self.app.svc.resumen_semana(self.ref, ahora_s=w.ahora_s())
        hoy = date.today()
        avance = min(1.0, r.llevas_s / r.meta_s) if r.meta_s else 1.0
        controles: list[ft.Control] = [
            ft.Row([w.dato("Llevas", w.dur(r.llevas_s), grande=True),
                    w.dato("Meta de la semana", w.dur(r.meta_s), grande=True)],
                   alignment=ft.MainAxisAlignment.SPACE_BETWEEN),
            ft.ProgressBar(value=avance, bar_height=10),
        ]
        if r.meta_s == 0:
            controles.append(ft.Text("Esta semana no tiene días laborales.", size=14))
        elif r.faltan_s > 0:
            controles.append(ft.Text(f"Te faltan {w.dur(r.faltan_s)} para completar las {w.dur(r.meta_s)} de la semana.",
                                     size=15, weight=ft.FontWeight.W_500, color=w.AMBAR))
            if r.salida_hoy_s is not None and r.dias_restantes == 1:
                controles.append(ft.Text(f"Hoy completas la semana a las {w.hora(r.salida_hoy_s, False)}.", size=14))
            elif r.dias_restantes:
                controles.append(ft.Text(
                    f"Quedan {r.dias_restantes} día(s) laboral(es): unas {w.dur(r.por_dia_s)} por día (más colación).",
                    size=14))
            elif r.lunes <= hoy:
                controles.append(ft.Text("Ya no quedan días laborales en esta semana.", size=13,
                                         color=ft.Colors.ON_SURFACE_VARIANT))
        else:
            extra = f" (+{w.dur(r.exceso_s)} sobre la meta)" if r.exceso_s else ""
            controles.append(ft.Text(f"¡Semana completa!{extra}", size=15, weight=ft.FontWeight.W_500, color=w.VERDE))
        controles.append(ft.Row([
            w.dato("Horas extra", w.dur(r.he_s), w.VERDE if r.he_s else None),
            w.dato("Faltantes", w.dur(r.faltante_s), w.ROJO if r.faltante_s else None),
            w.dato("Saldo", w.dur_signo(r.saldo_s), w.VERDE if r.saldo_s > 0 else w.ROJO if r.saldo_s < 0 else None),
        ], alignment=ft.MainAxisAlignment.SPACE_BETWEEN, wrap=True))
        controles.append(ft.Text("Saldo = horas extra − faltantes de los días ya cerrados (con ingreso y salida).",
                                 size=11, color=ft.Colors.ON_SURFACE_VARIANT))
        if r.sin_registro:
            controles.append(ft.Text(
                "Sin registro: " + ", ".join(w.fecha_corta(f) for f in r.sin_registro)
                + ". Cuentan en la meta; tócalos abajo para registrarlos si trabajaste.", size=12, color=w.AMBAR))
        return w.tarjeta(*controles, titulo="Mi semana", icono=ft.Icons.DATE_RANGE)

    def _tarjeta_vacaciones(self) -> ft.Control:
        v = self.app.svc.saldo_vacaciones()
        gris = ft.Colors.ON_SURFACE_VARIANT
        controles: list[ft.Control] = []
        if v.configurado:
            controles.append(ft.Row([
                w.dato("Disponibles", num_dias(v.disponibles), w.VERDE if v.disponibles > 0 else w.ROJO, grande=True),
                w.dato("Tomados", num_dias(v.tomados)),
                w.dato("Programados", num_dias(v.programados), w.AMBAR if v.programados else None),
            ], alignment=ft.MainAxisAlignment.SPACE_BETWEEN, wrap=True))
            origen = f"Saldo según RR.HH. al {w.fecha_corta(v.corte)}: {num_dias(v.saldo_inicial)} día(s)"
            if v.acumulado:
                origen += f" + {num_dias(v.acumulado)} ganados desde entonces"
            controles.append(ft.Text(origen + ". Días hábiles.", size=12, color=gris))
            if v.disponibles < 0:
                controles.append(ft.Text("Tienes más días marcados que tu saldo: revisa con RR.HH.", size=13,
                                         color=w.ROJO))
        else:
            controles.append(ft.Text("Pregúntale a RR.HH. cuántos días de vacaciones tienes disponibles y anótalos "
                                     "aquí: la app los irá descontando cada vez que marques vacaciones.", size=13))
            if v.tomados or v.programados:
                controles.append(ft.Text(f"Ya tienes {v.tomados + v.programados} día(s) de vacaciones marcados.",
                                         size=12, color=gris))
        for t in v.tramos[:6]:
            controles.append(ft.Row([
                ft.Icon(ft.Icons.FLIGHT_TAKEOFF if t.futuro else ft.Icons.CHECK_CIRCLE_OUTLINE, size=18,
                        color=w.AMBAR if t.futuro else gris),
                ft.Column([
                    ft.Text(rango_corto(t.desde, t.hasta), weight=ft.FontWeight.W_500),
                    ft.Text(f"{t.dias} día{'s' if t.dias != 1 else ''} hábil{'es' if t.dias != 1 else ''}"
                            + (" · programado" if t.futuro else " · tomado"), size=12, color=gris),
                ], spacing=0, expand=True),
            ]))
        if len(v.tramos) > 6:
            controles.append(ft.Text(f"… y {len(v.tramos) - 6} tramo(s) más antiguos.", size=12, color=gris))
        controles.append(ft.Row([
            ft.FilledTonalButton("Tomar vacaciones", icon=ft.Icons.BEACH_ACCESS,
                                 on_click=lambda _: self._dialogo_ausencia("vacaciones")),
            ft.TextButton("Editar saldo" if v.configurado else "Anotar mi saldo", icon=ft.Icons.EDIT,
                          on_click=lambda _: self._dialogo_saldo_vacaciones()),
        ], wrap=True))
        return w.tarjeta(*controles, titulo="Mis vacaciones", icono=ft.Icons.BEACH_ACCESS)

    def _dialogo_saldo_vacaciones(self) -> None:
        cfg = self.app.svc.cfg
        estado = {"fecha": calc.to_date(cfg.vac_saldo_fecha) if cfg.vac_saldo_fecha else date.today()}
        dias = ft.TextField(label="Días disponibles según RR.HH.", width=290,
                            value=num_dias(cfg.vac_saldo_dias) if cfg.vac_saldo_dias is not None else "",
                            keyboard_type=ft.KeyboardType.NUMBER)
        b_fecha = ft.OutlinedButton(icon=ft.Icons.EVENT)
        acumular = ft.Switch(value=cfg.vac_acumular)
        fila_acumular = ft.Row([acumular, ft.Text("Sumar lo que voy ganando (1,25 días por mes)", size=13,
                                                  expand=True)])
        anuales = ft.TextField(label="Días por año (15 + progresivos)", width=290, value=num_dias(cfg.vac_dias_anuales),
                               keyboard_type=ft.KeyboardType.NUMBER)
        error = ft.Text("", size=12, color=w.ROJO)

        def pintar():
            b_fecha.content = f"Saldo al: {w.fecha_corta(estado['fecha'])}"
            anuales.visible = bool(acumular.value)
            self.page.update()

        def cambio_fecha(e):
            if e.control.value:
                estado["fecha"] = a_fecha(e.control.value)
                pintar()

        b_fecha.on_click = lambda _: self.page.show_dialog(ft.DatePicker(
            value=estado["fecha"], first_date=date(2015, 1, 1), last_date=date(date.today().year + 1, 12, 31),
            on_change=cambio_fecha))
        acumular.on_change = lambda _: pintar()

        def numero(txt) -> float:
            try:
                return float((txt or "").strip().replace(",", "."))
            except ValueError:
                raise ValueError("Escribe un número de días (ej. 15 o 7,5).") from None

        def guardar(_, borrar: bool = False):
            try:
                if borrar:
                    self.app.svc.guardar_saldo_vacaciones(None, None)
                else:
                    self.app.svc.guardar_saldo_vacaciones(numero(dias.value), estado["fecha"], acumular.value,
                                                          numero(anuales.value or "15"))
            except ValueError as exc:
                error.value = str(exc)
                self.page.update()
                return
            self.page.pop_dialog()
            w.snack(self.page, "Saldo de vacaciones guardado." if not borrar else "Saldo quitado.", w.VERDE)
            self.app.refrescar()

        acciones = [ft.TextButton("Cancelar", on_click=lambda _: self.page.pop_dialog()),
                    ft.FilledButton("Guardar", on_click=guardar)]
        if cfg.vac_saldo_dias is not None:
            acciones.insert(0, ft.TextButton("Quitar", on_click=lambda e: guardar(e, borrar=True),
                                             style=ft.ButtonStyle(color=w.ROJO)))
        self.page.show_dialog(ft.AlertDialog(
            title=ft.Text("Mi saldo de vacaciones", size=20),
            content=ft.Container(width=320, content=ft.Column([
                ft.Text("Anota los días hábiles que te informó RR.HH. y la fecha de ese saldo. Las vacaciones "
                        "que marques desde esa fecha se irán descontando.", size=13),
                dias, b_fecha, fila_acumular, anuales,
                ft.Text("Activa «Sumar» solo si RR.HH. te dio el saldo sin contar lo que vas ganando mes a mes.",
                        size=11, color=ft.Colors.ON_SURFACE_VARIANT),
                error,
            ], tight=True, spacing=10, scroll=ft.ScrollMode.AUTO)),
            actions=acciones,
        ))
        pintar()

    def _fila_dia(self, c: calc.DayCalc, d) -> ft.Control:
        etiquetas = []
        if c.tipo != "laboral":
            etiquetas.append(w.chip(w.TIPO_ETIQUETA.get(c.tipo, c.tipo), w.AMBAR))
        if d and d.cambioDe:
            etiquetas.append(w.chip("Cambio de día", w.AMBAR))
        if d and d.motivoHE:
            etiquetas.append(w.chip(d.motivoHE[:30], w.VERDE))
        if c.extras_s:
            refs = ", ".join(b.get("ref") or "Extra" for b in d.extras)
            etiquetas.append(w.chip(f"{refs} {w.dur(c.extras_s)}", w.AMBAR))
        if c.estado == "sin_registro" and c.laboral:
            etiquetas.append(w.chip("Sin registro", w.ROJO))
        elif c.estado in ("en_curso", "incompleto"):
            etiquetas.append(w.chip("Incompleto", w.AMBAR))
        horario = f"{(d.ingreso or '—')[:5]} – {(d.salida or '—')[:5]}" if d else "—"
        saldo = ft.Text(w.dur_signo(c.saldo_s) if c.estado == "completo" else "",
                        color=w.VERDE if c.saldo_s > 0 else w.ROJO if c.saldo_s < 0 else None,
                        weight=ft.FontWeight.BOLD)
        return ft.Container(
            on_click=lambda _, f=c.fecha: abrir_editor(self.app, f, self.app.refrescar), ink=True, border_radius=8,
            padding=ft.Padding.symmetric(vertical=6, horizontal=4),
            content=ft.Row([
                ft.Column([ft.Text(w.fecha_corta(c.fecha), weight=ft.FontWeight.W_500),
                           ft.Text(f"{horario} · {w.dur(c.trabajadas_s)} trab.", size=12,
                                   color=ft.Colors.ON_SURFACE_VARIANT),
                           ft.Row(etiquetas, wrap=True, spacing=4)], spacing=2, expand=True),
                saldo,
            ]),
        )

    # ------------------------------------------------------------------ acciones
    def _mover(self, k: int) -> None:
        cfg = self.app.svc.cfg
        if cfg.periodo_modo == "semana":
            self.ref += timedelta(days=7 * k)
        elif cfg.periodo_modo in ("mes", "ciclo"):
            anio, mes = calc._mover_mes(self.ref.year, self.ref.month, k)
            self.ref = calc._fecha_ajustada(anio, mes, self.ref.day)
        self._confirmando_borrado = False
        self.app.refrescar()

    # ------------------------------------------------------------------ vacaciones / licencia en rango
    def _dialogo_ausencia(self, inicial: str = "vacaciones") -> None:
        hoy = date.today()
        estado = {"desde": hoy, "hasta": hoy}
        saldo = self.app.svc.saldo_vacaciones()
        tipo = ft.Dropdown(label="Marcar como", value=inicial, width=290, dense=True, options=[
            *[ft.DropdownOption(key=k, text=w.TIPO_ETIQUETA[k]) for k in ("vacaciones", "licencia", "permiso", "feriado")],
            ft.DropdownOption(key="quitar", text="Quitar marca (volver a laboral)"),
        ])
        b_desde = ft.OutlinedButton(icon=ft.Icons.EVENT)
        b_hasta = ft.OutlinedButton(icon=ft.Icons.EVENT)
        info = ft.Text("", size=12, color=ft.Colors.ON_SURFACE_VARIANT)
        error = ft.Text("", size=12, color=w.ROJO)

        def pintar():
            b_desde.content = f"Desde: {w.fecha_corta(estado['desde'])}"
            b_hasta.content = f"Hasta: {w.fecha_corta(estado['hasta'])}"
            n = (estado["hasta"] - estado["desde"]).days + 1
            info.value = (f"{n} día(s) corridos. Solo cambian los días laborales; los fines de semana, los "
                          "feriados ya marcados y los días con marcas no se tocan." if n > 0 else "")
            if n > 0 and tipo.value == "vacaciones":
                habiles = self.app.svc.contar_habiles(estado["desde"], estado["hasta"])
                info.value = f"Descuenta {habiles} día(s) hábil(es)"
                if saldo.configurado:
                    info.value += f": te quedarían {num_dias(saldo.disponibles - habiles)}"
                info.value += (". Si hay un feriado en medio, márcalo antes como «Feriado» para que no se "
                               "descuente.")
            error.value = "" if n > 0 else "La fecha «Hasta» es anterior a «Desde»."
            self.page.update()

        def elegir(campo):
            def cambio(e):
                if e.control.value:
                    estado[campo] = a_fecha(e.control.value)
                    if estado["hasta"] < estado["desde"]:
                        estado["hasta" if campo == "desde" else "desde"] = estado[campo]
                    pintar()
            self.page.show_dialog(ft.DatePicker(value=estado[campo], first_date=date(hoy.year - 1, 1, 1),
                                                last_date=date(hoy.year + 2, 12, 31), on_change=cambio))

        tipo.on_select = lambda _: pintar()
        b_desde.on_click = lambda _: elegir("desde")
        b_hasta.on_click = lambda _: elegir("hasta")

        def aplicar(_):
            elegido = None if tipo.value == "quitar" else tipo.value
            try:
                r = self.app.svc.marcar_rango(estado["desde"], estado["hasta"], elegido)
            except ValueError as exc:
                error.value = str(exc)
                self.page.update()
                return
            self.page.pop_dialog()
            if elegido:
                msg = f"Marqué {len(r['marcados'])} día(s) como {w.TIPO_ETIQUETA[elegido].lower()}."
            else:
                msg = f"Quité la marca de {len(r['marcados'])} día(s)."
            if r["con_marcas"]:
                msg += " No toqué " + ", ".join(w.fecha_corta(f) for f in r["con_marcas"]) + " porque tienen marcas."
            if r.get("feriados"):
                msg += " " + ", ".join(w.fecha_corta(f) for f in r["feriados"]) + " sigue(n) como feriado."
            w.snack(self.page, msg, w.VERDE)
            self.app.refrescar()

        self.page.show_dialog(ft.AlertDialog(
            title=ft.Text("Marcar días", size=20),
            content=ft.Container(width=320, content=ft.Column([tipo, b_desde, b_hasta, info, error], tight=True,
                                                              spacing=10, scroll=ft.ScrollMode.AUTO)),
            actions=[ft.TextButton("Cancelar", on_click=lambda _: self.page.pop_dialog()),
                     ft.FilledButton("Aplicar", on_click=aplicar)],
        ))
        pintar()

    def _registrar_anterior(self, _) -> None:
        fecha = self.p.sin_registro[0] if self.p.sin_registro else min(date.today(), self.p.hasta)
        abrir_editor(self.app, fecha, self.app.refrescar)

    async def _borrar(self, _) -> None:
        if not self._confirmando_borrado:
            self._confirmando_borrado = True
            self.app.refrescar()
            await asyncio.sleep(4)
            if self._confirmando_borrado:
                self._confirmando_borrado = False
                self.app.refrescar()
            return
        self._confirmando_borrado = False
        n = self.app.svc.borrar_periodo(self.p.desde, self.p.hasta)
        w.snack(self.page, f"Se borraron {n} día(s) del periodo.")
        self.app.refrescar()

    def _dialogo_modo(self) -> None:
        cfg = self.app.svc.cfg
        modo = ft.RadioGroup(value=cfg.periodo_modo, content=ft.Column(
            [ft.Radio(value=k, label=v) for k, v in MODOS.items()]))
        dia_ciclo = ft.TextField(label="Día de inicio del ciclo", value=str(cfg.ciclo_dia_inicio), width=200,
                                 keyboard_type=ft.KeyboardType.NUMBER)
        desde = ft.TextField(label="Desde (AAAA-MM-DD)", value=cfg.periodo_desde or "", width=200)
        hasta = ft.TextField(label="Hasta (AAAA-MM-DD)", value=cfg.periodo_hasta or "", width=200)
        error = ft.Text("", color=w.ROJO, size=12)

        def guardar(_):
            try:
                nuevo = replace(cfg, periodo_modo=modo.value, ciclo_dia_inicio=max(1, min(28, int(dia_ciclo.value or 25))),
                                periodo_desde=desde.value.strip() or None, periodo_hasta=hasta.value.strip() or None)
                calc.rango_periodo(nuevo.periodo_modo, self.ref, nuevo.ciclo_dia_inicio,
                                   nuevo.periodo_desde, nuevo.periodo_hasta)
            except ValueError as exc:
                error.value = str(exc)
                self.page.update()
                return
            self.app.svc.guardar_config(nuevo)
            if nuevo.periodo_modo == "fechas":
                self.ref = calc.to_date(nuevo.periodo_desde)
            self.page.pop_dialog()
            self.app.refrescar()

        self.page.show_dialog(ft.AlertDialog(
            title=ft.Text("Periodo a contabilizar"),
            content=ft.Column([modo, dia_ciclo, ft.Row([desde, hasta], wrap=True), error], tight=True),
            actions=[ft.TextButton("Cancelar", on_click=lambda _: self.page.pop_dialog()),
                     ft.FilledButton("Aplicar", on_click=guardar)],
        ))
