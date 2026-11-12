"""Pestaña Hoy: marcar ingreso/salida, plan de jornada, avance, avisos y conciliación Workera."""
from __future__ import annotations

from datetime import date, timedelta
from typing import Optional

import flet as ft

from core.calculator import H, PlanOption
from services.attendance_resolver import (
    AV_FALTA_ENTRADA, AV_FALTA_SALIDA, AV_MARCAS_CERCANAS, AV_MARCAS_INTERMEDIAS, AV_NO_CUADRA_ALERTA,
    INGRESO, SALIDA, ResolucionDia,
)
from services.jornada_service import EstadoHoy
from ui import widgets as w
from ui.editor_dia import PLAN_ETIQUETA, abrir_editor

AVISO_TEXTO = {
    AV_FALTA_ENTRADA: "Falta la marca de entrada",
    AV_FALTA_SALIDA: "Aún no hay marca de salida",
    AV_MARCAS_CERCANAS: "Dos marcas con menos de 2 h entre sí: revisa",
    AV_MARCAS_INTERMEDIAS: "Hay marcas intermedias (se usó la primera y la última)",
    AV_NO_CUADRA_ALERTA: "Tus marcas no calzan con la alerta de Workera",
}
ROL_TEXTO = {"ingreso": "Ingreso", "salida": "Salida", "rebote": "Duplicada", "intermedia": "Intermedia",
             "pendiente": "Por confirmar", "ignorada": "Ignorada"}
VENTANA_AVISO_S = 30 * 60


class HoyView:
    def __init__(self, app):
        self.app = app
        self.page = app.page
        self.lista = ft.ListView(padding=12, spacing=10, expand=True)
        self.st: Optional[EstadoHoy] = None
        self.fecha = date.today()
        self._lbl_reloj = ft.Text(size=13, color=ft.Colors.ON_SURFACE_VARIANT)
        self._lbl_llevas = ft.Text(size=13)
        self._lbl_falta = ft.Text(size=13)
        self._barra = ft.ProgressBar(value=0, bar_height=10)
        self._avisado: set[tuple[date, int]] = set()
        self._posponer_hasta: Optional[int] = None
        self._ticks = 0

    def construir(self) -> ft.Control:
        return self.lista

    # ------------------------------------------------------------------ pintado
    def refrescar(self) -> None:
        self.fecha = date.today()
        self.cfg = self.app.svc.cfg
        self.seg = self.cfg.mostrar_segundos
        st = self.st = self.app.svc.estado(self.fecha, w.ahora_s())
        c: list[ft.Control] = [self._cabecera(st), self._linea_semana()]
        res = st.resolucion
        if res and res.pregunta:
            c.append(self._banner_pregunta(res))
        if st.day.ingreso is None:
            c.append(self._panel_sin_ingreso(st))
        else:
            c.extend(self._avisos(st))
            c.append(self._panel_jornada(st))
        if res:
            c.append(self._panel_workera(st, res))
        self.lista.controls = c
        self.tick(actualizar=False)

    def _cabecera(self, st: EstadoHoy) -> ft.Control:
        chips = [w.chip(w.TIPO_ETIQUETA.get(st.calc.tipo, st.calc.tipo), w.AZUL if st.laboral else w.AMBAR)]
        if st.day.cambioDe:
            chips.append(w.chip(f"Cambio del {st.day.cambioDe}", w.AMBAR, ft.Icons.SWAP_HORIZ))
        fuente = self.app.fuente()
        if fuente == "ninguna":
            estado_sync = w.chip("Registro manual", w.AZUL, ft.Icons.TOUCH_APP)
        elif self.app.sincronizando:
            estado_sync = w.chip("Sincronizando…", w.AZUL, ft.Icons.SYNC)
        elif self.app.puede_sincronizar():
            ultima = self.app.db.get_meta("ultima_sync")
            estado_sync = w.chip(f"Workera {ultima[11:16]}" if ultima else "Workera sin sincronizar",
                                 w.VERDE if ultima else w.AMBAR, ft.Icons.CLOUD_DONE if ultima else ft.Icons.CLOUD_OFF)
        else:
            estado_sync = w.chip("Workera no configurado", w.AMBAR, ft.Icons.CLOUD_OFF)
        if self.app.push_cfg().listo:
            chips.append(w.chip("Aviso en el teléfono", w.VERDE, ft.Icons.NOTIFICATIONS_ACTIVE))
        fila: list[ft.Control] = [
            ft.Column([ft.Text(w.fecha_larga(self.fecha), size=20, weight=ft.FontWeight.BOLD), self._lbl_reloj,
                       ft.Row(chips + [estado_sync], wrap=True, spacing=6)], spacing=4, expand=True)]
        if fuente != "ninguna" and self.app.sincronizando:
            fila.append(ft.Container(ft.ProgressRing(width=22, height=22, stroke_width=3), padding=13))
        elif fuente != "ninguna":
            fila.append(ft.IconButton(ft.Icons.SYNC, tooltip="Sincronizar con Workera",
                                      on_click=lambda _: self.page.run_task(self.app.sincronizar)))
        return ft.Row(fila, vertical_alignment=ft.CrossAxisAlignment.START)

    def _linea_semana(self) -> ft.Control:
        """Resumen corto de la semana: cuánto llevo, cuánto falta y cuánto toca por día."""
        r = self.app.svc.resumen_semana(self.fecha, hoy=self.fecha, ahora_s=w.ahora_s())
        if r.meta_s == 0:
            texto, color = "Semana sin días laborales.", ft.Colors.ON_SURFACE_VARIANT
        elif r.faltan_s > 0:
            texto = f"Semana: llevas {w.dur(r.llevas_s)} de {w.dur(r.meta_s)} · faltan {w.dur(r.faltan_s)}"
            if r.salida_hoy_s is not None and r.dias_restantes == 1:
                texto += f" · la completas hoy a las {w.hora(r.salida_hoy_s, False)}"
            elif r.dias_restantes > 1 and r.por_dia_s is not None:
                texto += f" · {w.dur(r.por_dia_s)} por día en {r.dias_restantes} días"
            color = w.AZUL
        else:
            texto = f"Semana completa: {w.dur(r.llevas_s)} de {w.dur(r.meta_s)}"
            texto += f" (+{w.dur(r.exceso_s)})" if r.exceso_s else ""
            color = w.VERDE
        return ft.Container(
            content=ft.Row([ft.Icon(ft.Icons.DATE_RANGE, size=18, color=color),
                            ft.Text(texto, size=13, color=color, expand=True)], spacing=6),
            bgcolor=ft.Colors.with_opacity(0.08, color), border_radius=10,
            padding=ft.Padding.symmetric(horizontal=10, vertical=8),
            on_click=lambda _: self.app.ir_a(1), ink=True,
        )

    def _banner_pregunta(self, res: ResolucionDia) -> ft.Control:
        p = res.pregunta
        return ft.Container(
            bgcolor=ft.Colors.with_opacity(0.15, w.AMBAR), border_radius=12, padding=12,
            content=ft.Column([
                ft.Row([ft.Icon(ft.Icons.HELP_OUTLINE, color=w.AMBAR), ft.Text(p.mensaje, expand=True)]),
                ft.Row([
                    ft.FilledButton(p.etiqueta_boton, on_click=lambda _: self._accion(
                        lambda: self.app.svc.mover_a_salida(self.fecha, p.checksum), "Listo: la marca quedó como salida.")),
                    ft.TextButton("Es turno de tarde", on_click=lambda _: self._accion(
                        lambda: self.app.svc.marcar_como_ingreso(self.fecha, p.checksum),
                        "Listo: la marca quedó como ingreso (turno de tarde).")),
                ], wrap=True),
            ]),
        )

    def _panel_sin_ingreso(self, st: EstadoHoy) -> ft.Control:
        nota = [] if st.laboral else [ft.Text(
            f"Hoy es {w.TIPO_ETIQUETA.get(st.calc.tipo, '').lower()}: al marcar te preguntaré cómo contarlo.",
            size=12, color=ft.Colors.ON_SURFACE_VARIANT)]
        return w.tarjeta(
            *nota,
            ft.Row([
                ft.FilledButton("Marcar ingreso · Ahora", icon=ft.Icons.LOGIN,
                                on_click=lambda _: self._marcar_ingreso(w.ahora_s())),
                ft.OutlinedButton("Elegir hora", icon=ft.Icons.SCHEDULE, on_click=lambda _: w.selector_hora(
                    self.page, "Hora de ingreso", w.ahora_s(), self._marcar_ingreso)),
            ], wrap=True),
            titulo="Ingreso", icono=ft.Icons.LOGIN,
        )

    def _panel_jornada(self, st: EstadoHoy) -> ft.Control:
        d, c, cfg = st.day, st.calc, self.cfg
        fuente_ing = d.fuente.get("ingreso")
        col_ing = [w.dato("Ingreso", d.ingreso or "—")]
        if fuente_ing:
            col_ing.append(w.chip(w.FUENTE_ETIQUETA.get(fuente_ing, fuente_ing), w.AZUL))
        if d.salida:
            col_sal = [w.dato("Salida", d.salida, grande=True)]
            if d.fuente.get("salida"):
                col_sal.append(w.chip(w.FUENTE_ETIQUETA.get(d.fuente["salida"], d.fuente["salida"]), w.AZUL))
        else:
            col_sal = [w.dato("Salida estimada", w.hora(st.salida_estimada_s, self.seg), color=w.VERDE, grande=True)]
        controles: list[ft.Control] = [
            ft.Row([ft.Column(col_ing, spacing=4), ft.Column(col_sal, spacing=4)],
                   alignment=ft.MainAxisAlignment.SPACE_BETWEEN),
        ]
        if st.laboral:
            controles += [self._barra, ft.Row([self._lbl_llevas, self._lbl_falta],
                                              alignment=ft.MainAxisAlignment.SPACE_BETWEEN)]
            plan = d.plan or "normal"
            etiqueta = PLAN_ETIQUETA.get(plan, plan) + (f" ({w.dur(d.antes)} antes)" if plan == "adel" else "")
            fila_plan = [w.chip(f"Plan: {etiqueta}", w.AZUL)]
            if not d.salida:
                fila_plan.append(ft.TextButton("Cambiar plan", on_click=lambda _: self._dialogo_plan()))
            controles.append(ft.Row(fila_plan, wrap=True))
        else:
            controles.append(self._lbl_llevas)
            controles.append(ft.Text("Día no laboral: todo lo trabajado cuenta como horas extra (sin colación).",
                                     size=12, color=ft.Colors.ON_SURFACE_VARIANT))

        tope = f" / tope {w.dur(cfg.tope_s)}" if cfg.tope_s else ""
        saldo_txt = "Saldo de la semana" + (" (si sales ahora)" if not d.salida else "")
        controles.append(ft.Row([
            w.dato(saldo_txt, w.dur_signo(st.saldo_semana_s) + tope,
                   color=w.ROJO if cfg.tope_s and st.saldo_semana_s > cfg.tope_s else None),
            w.dato("Hora límite del tope", w.hora(st.hora_limite_s, self.seg)) if st.hora_limite_s else ft.Container(),
        ], alignment=ft.MainAxisAlignment.SPACE_BETWEEN))

        if d.salida:
            controles.append(ft.Row([
                w.dato("Trabajadas", w.dur(c.trabajadas_s)),
                w.dato("HE", w.dur(c.he_s), color=w.VERDE if c.he_s else None),
                w.dato("Faltante", w.dur(c.faltante_s), color=w.ROJO if c.faltante_s else None),
                w.dato("Saldo día", w.dur_signo(c.saldo_s)),
            ], alignment=ft.MainAxisAlignment.SPACE_BETWEEN, wrap=True))
            if c.he_excedente_s:
                controles.append(ft.Text(f"{w.dur(c.he_excedente_s)} sobre el máximo diario de HE no se contabilizan.",
                                         size=12, color=w.AMBAR))
            if c.he_s:
                controles.append(ft.Row([
                    ft.Text(f"Motivo HE: {d.motivoHE or 'sin indicar'}", expand=True, size=13),
                    ft.TextButton("Editar", on_click=lambda _: self._dialogo_motivo()),
                ]))
        else:
            controles.append(ft.Row([
                ft.FilledButton("Marcar salida · Ahora", icon=ft.Icons.LOGOUT,
                                on_click=lambda _: self._marcar_salida(w.ahora_s())),
                ft.OutlinedButton("Elegir hora", icon=ft.Icons.SCHEDULE, on_click=lambda _: w.selector_hora(
                    self.page, "Hora de salida", w.ahora_s(), self._marcar_salida)),
            ], wrap=True))

        if d.extras:
            controles.append(ft.Row([w.chip(f"{b.get('ref') or 'Extra'} {b.get('inicio', '')[:5]}–{b.get('fin', '')[:5]}",
                                            w.AMBAR, ft.Icons.WORK_HISTORY) for b in d.extras], wrap=True))
        acciones = [ft.TextButton("Editar día", icon=ft.Icons.EDIT,
                                  on_click=lambda _: abrir_editor(self.app, self.fecha, self.app.refrescar))]
        if d.ingreso or d.salida:
            acciones.append(ft.TextButton("⇄ Invertir Entrada/Salida",
                                          on_click=lambda _: self._accion(lambda: self.app.svc.invertir(self.fecha),
                                                                        "Invertí ingreso y salida.")))
        if d.cambioDe:
            acciones.append(ft.TextButton("Deshacer cambio de día", icon=ft.Icons.UNDO,
                                          on_click=lambda _: self._accion(lambda: self.app.svc.deshacer_cambio(self.fecha),
                                                                        "Cambio de día deshecho.")))
        controles.append(ft.Row(acciones, wrap=True))
        return w.tarjeta(*controles, titulo="Jornada de hoy", icono=ft.Icons.TIMER)

    def _avisos(self, st: EstadoHoy) -> list[ft.Control]:
        out: list[ft.Control] = []
        ahora = w.ahora_s()
        if st.deuda and not st.day.salida:
            botones = [] if st.day.plan == "comp" else [ft.TextButton(
                "Usar Compensar", on_click=lambda _: self._elegir_plan("comp", 0))]
            out.append(w.tarjeta(ft.Text(f"Debes recuperar {w.dur(st.deuda['deuda_s'])} esta semana. "
                                         f"Sugerido hoy: {w.dur(st.deuda['sugerido_hoy_s'])}."), *botones,
                                 titulo="Deuda pendiente", color=w.AMBAR, icono=ft.Icons.WARNING_AMBER))
        if st.cierre:
            cm = st.cierre["compensar_manana_s"]
            texto = (f"Saldo proyectado de la semana: {w.dur_signo(st.cierre['saldo_proyectado_s'])}. "
                     + (f"¿Compensar mañana ({w.fecha_corta(st.cierre['manana'])}) "
                        f"{'saliendo ' + w.dur(cm) + ' antes' if cm > 0 else 'quedándote ' + w.dur(-cm) + ' más'}?"
                        if cm else "La semana cierra en cero."))
            out.append(w.tarjeta(ft.Text(texto), ft.Row([
                ft.FilledButton("Sí", on_click=lambda _: self._responder_cierre("si", st.cierre["manana"])),
                ft.TextButton("No", on_click=lambda _: self._responder_cierre("no", None)),
            ]), titulo="Cierre de semana", color=w.AZUL, icono=ft.Icons.EVENT_AVAILABLE))
        if st.hora_limite_s and not st.day.salida and ahora > st.hora_limite_s:
            out.append(w.tarjeta(ft.Text(f"Pasaste la hora límite ({w.hora(st.hora_limite_s, self.seg)}): "
                                         f"ya superas el tope de {w.dur(self.cfg.tope_s)} de saldo."),
                                 titulo="Hora límite", color=w.ROJO, icono=ft.Icons.ALARM))
        return out

    def _panel_workera(self, st: EstadoHoy, res: ResolucionDia) -> ft.Control:
        controles: list[ft.Control] = []
        if res.conciliacion:
            cc = res.conciliacion
            controles.append(w.chip(cc.badge, w.VERDE if cc.jornada_validada else w.AZUL, ft.Icons.VERIFIED
                                    if cc.jornada_validada else ft.Icons.INFO_OUTLINE))
        for a in res.asignaciones:
            origen = "RR.HH." if a.checksum.startswith("SOL") else "reloj"
            fila = [ft.Text(a.hora, weight=ft.FontWeight.BOLD), ft.Text(f"{origen}: {a.tipo_declarado}", size=12),
                    w.chip(ROL_TEXTO.get(a.rol, a.rol), w.VERDE if a.rol in (INGRESO, SALIDA) else w.AMBAR)]
            if a.badge:
                fila.append(w.chip(a.badge, w.AMBAR if a.inferido_por_secuencia else w.AZUL))
            controles.append(ft.Row(fila, wrap=True, spacing=6))
        for s in res.sugerencias:
            if getattr(st.day, s.campo):
                continue
            nombre = "ingreso" if s.campo == INGRESO else "salida"
            controles.append(ft.Row([
                ft.Text(f"Autocompletar {nombre} {s.hora}", expand=True, size=13),
                ft.TextButton("Aplicar", on_click=lambda _, campo=s.campo: self._accion(
                    lambda: self.app.svc.aplicar_sugerencia(self.fecha, campo), f"{nombre.capitalize()} aplicado.")),
            ]))
            controles.append(ft.Text(s.motivo, size=11, color=ft.Colors.ON_SURFACE_VARIANT))
        for av in res.avisos:
            if av == AV_FALTA_SALIDA and not st.day.salida:
                continue
            controles.append(ft.Text("• " + AVISO_TEXTO.get(av, av), size=12, color=w.AMBAR))
        if self.app.db.get_overrides(self.fecha):
            controles.append(ft.TextButton("Deshacer mis ajustes", icon=ft.Icons.UNDO, on_click=lambda _: self._accion(
                lambda: self.app.svc.deshacer_ajustes_workera(self.fecha), "Volví a la lectura automática de Workera.")))
        return w.tarjeta(*controles, titulo="Marcas Workera", icono=ft.Icons.FINGERPRINT)

    # ------------------------------------------------------------------ reloj
    def tick(self, actualizar: bool = True) -> None:
        st = self.st
        if st is None:
            return
        if date.today() != self.fecha:          # cambió el día
            self.refrescar()
            self.page.update()
            return
        reconstruir = False
        ahora = w.ahora_s()
        self._lbl_reloj.value = w.hora(ahora, self.seg)
        ing = st.day.ingreso
        if ing and not st.day.salida:
            from core.calculator import parse_hms
            llevas = (ahora - parse_hms(ing)) % 86400
            self._lbl_llevas.value = f"Llevas {w.dur(llevas, self.seg)}"
            if st.salida_estimada_s is not None:
                falta = st.salida_estimada_s - ahora
                total = max(1, st.salida_estimada_s - parse_hms(ing))
                self._barra.value = max(0.0, min(1.0, llevas / total))
                self._lbl_falta.value = (f"Faltan {w.dur(falta, self.seg)}" if falta > 0
                                         else f"Pasaste {w.dur(-falta, self.seg)}")
                self._revisar_aviso_salida(st, ahora)
        elif ing and st.day.salida:
            self._barra.value = 1
            self._lbl_llevas.value = f"Trabajaste {w.dur(st.calc.trabajadas_s, self.seg)}"
            self._lbl_falta.value = ""
        self._ticks += 1
        if self._ticks % 60 == 0:               # recalcular saldo, avisos y hora límite cada minuto
            self.refrescar()
            reconstruir = True
        if not actualizar:
            return
        if reconstruir:
            self.page.update()
            return
        # Cada segundo solo cambian el reloj, el avance y la barra: se envían solo esos controles.
        for c in (self._lbl_reloj, self._lbl_llevas, self._lbl_falta, self._barra):
            try:
                c.update()
            except RuntimeError:            # control que no está en pantalla en este estado del día
                pass

    def _revisar_aviso_salida(self, st: EstadoHoy, ahora: int) -> None:
        aviso, salida = st.aviso_salida_s, st.salida_estimada_s
        clave = (self.fecha, salida)
        if aviso is None or clave in self._avisado:
            return
        if self._posponer_hasta is not None and ahora < self._posponer_hasta:
            return
        if aviso <= ahora <= salida + VENTANA_AVISO_S:
            self._avisado.add(clave)
            if self.cfg.aviso_sonido:
                try:
                    self.page.run_task(ft.HapticFeedback().vibrate)
                except Exception:
                    pass

            def posponer(_):
                self._avisado.discard(clave)
                self._posponer_hasta = w.ahora_s() + 5 * 60
                self.page.pop_dialog()

            self.page.show_dialog(ft.AlertDialog(
                title=ft.Text("Aviso de salida"),
                content=ft.Text(f"Tu salida es a las {w.hora(salida, self.seg)}."),
                actions=[ft.TextButton("Recordar en 5 min", on_click=posponer),
                         ft.FilledButton("OK", on_click=lambda _: self.page.pop_dialog())],
            ))

    # ------------------------------------------------------------------ acciones
    def _accion(self, fn, ok: str = "") -> None:
        try:
            fn()
        except ValueError as exc:
            w.snack(self.page, str(exc), w.ROJO)
        else:
            if ok:
                w.snack(self.page, ok, w.VERDE)
        self.app.refrescar()

    def _marcar_ingreso(self, seg: int) -> None:
        self.app.svc.marcar_ingreso(self.fecha, seg)
        self._posponer_hasta = None
        self.app.refrescar()
        st = self.st
        if st.calc.tipo in ("libre", "feriado") and not st.day.cambioDe:
            self._dialogo_no_laboral()
        elif st.laboral:
            if st.ultimo:
                self._dialogo_ultimo_dia(st)
            else:
                self._dialogo_plan()

    def _marcar_salida(self, seg: int) -> None:
        c = self.app.svc.marcar_salida(self.fecha, seg)
        self.app.refrescar()
        if c.he_s > 0:
            self._dialogo_motivo()

    def _elegir_plan(self, codigo: str, antes: int) -> None:
        self.app.svc.elegir_plan(self.fecha, codigo, antes)
        self._avisado = {k for k in self._avisado if k[0] != self.fecha}
        self.app.refrescar()

    def _responder_cierre(self, resp: str, manana: Optional[date]) -> None:
        self.app.svc.responder_cierre(self.fecha, resp)
        if resp == "si" and manana:
            self.app.svc.elegir_plan(manana, "comp")
            w.snack(self.page, f"Listo: {w.fecha_corta(manana)} quedará con plan Compensar.")
        self.app.refrescar()

    # ------------------------------------------------------------------ diálogos
    def _dialogo_plan(self) -> None:
        st = self.app.svc.estado(self.fecha, w.ahora_s())
        cab: list[ft.Control] = []
        if st.deuda:
            cab.append(ft.Text(f"Debes {w.dur(st.deuda['deuda_s'])} esta semana; se recomienda Compensar.",
                               color=w.AMBAR, size=13))

        def item(op: PlanOption) -> ft.Control:
            sub = f"Salida {w.hora(op.salida_s, self.seg)}" + (f" · {op.nota}" if op.nota else "")
            if not op.habilitada:
                sub += " · supera el tope"
            return ft.ListTile(
                title=ft.Text(op.etiqueta), subtitle=ft.Text(sub, size=12), disabled=not op.habilitada,
                trailing=w.chip("Recomendado", w.VERDE) if op.recomendada else None,
                on_click=lambda _, o=op: (self.page.pop_dialog(), self._elegir_plan(o.codigo, o.antes_s)),
            )

        self.page.show_dialog(ft.AlertDialog(
            title=ft.Text("¿Cómo será tu jornada hoy?"),
            content=ft.Container(width=420, content=ft.Column(cab + [item(o) for o in st.opciones],
                                                               scroll=ft.ScrollMode.AUTO, tight=True)),
            actions=[ft.TextButton("Cerrar", on_click=lambda _: self.page.pop_dialog())],
        ))

    def _dialogo_ultimo_dia(self, st: EstadoHoy) -> None:
        u = st.ultimo
        texto = f"Puedes retirarte a las {w.hora(u['salida_s'], True)}"
        texto += " para cerrar la semana en cero." if u["cierra_en_cero"] else \
            f" (máximo {w.dur(self.cfg.max_devolver_s)} por día; la semana no alcanza a quedar en cero)."

        def si(_):
            self.page.pop_dialog()
            self._elegir_plan("comp", 0)

        def otra(_):
            self.page.pop_dialog()
            self._dialogo_plan()

        self.page.show_dialog(ft.AlertDialog(
            title=ft.Text("Último día de la semana"), content=ft.Text(texto),
            actions=[ft.TextButton("Elegir otra opción", on_click=otra), ft.FilledButton("Sí", on_click=si)],
        ))

    def _dialogo_no_laboral(self) -> None:
        candidatos = self.app.svc.candidatos_cambio(self.fecha)

        def elegir(f: date):
            self.page.pop_dialog()
            self._accion(lambda: self.app.svc.cambio_de_dia(self.fecha, f))
            self._dialogo_plan()

        opciones: list[ft.Control] = [ft.Text("Jornada normal (cambio de día): ¿qué día de esta semana recuperas?",
                                              weight=ft.FontWeight.BOLD)]
        opciones += [ft.ListTile(title=ft.Text(w.fecha_larga(f)), leading=ft.Icon(ft.Icons.SWAP_HORIZ),
                                 on_click=lambda _, f=f: elegir(f)) for f in candidatos] or [
            ft.Text("No hay días laborales libres esta semana para cambiar.", size=12)]
        self.page.show_dialog(ft.AlertDialog(
            title=ft.Text(f"Hoy es {w.TIPO_ETIQUETA.get(self.st.calc.tipo, '').lower()}"),
            content=ft.Container(width=420, content=ft.Column(opciones, tight=True, scroll=ft.ScrollMode.AUTO)),
            actions=[ft.FilledButton("Todo como horas extra", on_click=lambda _: self.page.pop_dialog())],
        ))

    def _dialogo_motivo(self) -> None:
        campo = ft.TextField(label="Motivo de las horas extra", value=self.st.day.motivoHE if self.st else "",
                             multiline=True, autofocus=True)

        def guardar(_):
            self.app.svc.guardar_motivo(self.fecha, campo.value or "")
            self.page.pop_dialog()
            self.app.refrescar()

        self.page.show_dialog(ft.AlertDialog(
            title=ft.Text("Hiciste horas extra"), content=campo,
            actions=[ft.TextButton("Omitir", on_click=lambda _: self.page.pop_dialog()),
                     ft.FilledButton("Guardar", on_click=guardar)],
        ))
