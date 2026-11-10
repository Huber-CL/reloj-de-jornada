"""Editor de un día cualquiera (registrar días anteriores, corregir horas, extras, tipo de día)."""
from __future__ import annotations

from datetime import date, timedelta
from typing import Callable, Optional

import flet as ft

from core.calculator import PLANES, TIPOS_DIA, Day, fmt_hms
from ui import widgets as w

PLAN_ETIQUETA = {"normal": "Jornada normal", "comp": "Compensar", "adel": "Salir antes",
                 "he1": "+1 HE", "he2": "+2 HE", "tope": "Hasta el tope"}


def abrir_editor(app, fecha: date, al_guardar: Optional[Callable[[], None]] = None) -> None:
    page = app.page
    estado = {"fecha": fecha}

    titulo = ft.Text(size=18, weight=ft.FontWeight.BOLD)
    tipo = ft.Dropdown(label="Tipo de día", width=260,
                       options=[ft.DropdownOption(key="", text="Automático (según día)")]
                       + [ft.DropdownOption(key=t, text=w.TIPO_ETIQUETA[t]) for t in TIPOS_DIA])
    ingreso = ft.TextField(label="Ingreso (hh:mm:ss)", width=150)
    salida = ft.TextField(label="Salida (hh:mm:ss)", width=150)
    plan = ft.Dropdown(label="Plan", width=200, options=[ft.DropdownOption(key="", text="—")]
                       + [ft.DropdownOption(key=p, text=PLAN_ETIQUETA[p]) for p in PLANES])
    objetivo = ft.TextField(label="Meta del día (h)", width=150, keyboard_type=ft.KeyboardType.NUMBER)
    colacion = ft.TextField(label="Colación (min)", width=150, keyboard_type=ft.KeyboardType.NUMBER)
    motivo = ft.TextField(label="Motivo de las horas extra", multiline=True)
    nota = ft.TextField(label="Nota", multiline=True)
    extras_col = ft.Column(spacing=6)
    error = ft.Text("", color=w.ROJO, size=12)
    info = ft.Text("", size=12, color=ft.Colors.ON_SURFACE_VARIANT)

    def fila_extra(b: Optional[dict] = None) -> ft.Row:
        b = b or {}
        fila = ft.Row(spacing=6)
        fila.controls = [
            ft.TextField(label="Inicio", value=b.get("inicio", ""), width=95, dense=True),
            ft.TextField(label="Fin", value=b.get("fin", ""), width=95, dense=True),
            ft.TextField(label="Ref. (SVR, AAR…)", value=b.get("ref", ""), expand=True, dense=True),
            ft.IconButton(ft.Icons.DELETE_OUTLINE, on_click=lambda _: (extras_col.controls.remove(fila), page.update())),
        ]
        return fila

    def cargar() -> None:
        d = app.svc.dia(estado["fecha"])
        estado["day"] = d
        titulo.value = w.fecha_larga(d.fecha)
        tipo.value = d.tipo or ""
        ingreso.value, salida.value = d.ingreso or "", d.salida or ""
        plan.value = d.plan or ""
        objetivo.value = "" if d.objetivoH is None else str(d.objetivoH)
        colacion.value = "" if d.colacionMin is None else str(d.colacionMin)
        motivo.value, nota.value = d.motivoHE, d.nota
        extras_col.controls = [fila_extra(b) for b in d.extras]
        fuentes = ", ".join(f"{k}: {w.FUENTE_ETIQUETA.get(v, v)}" for k, v in d.fuente.items())
        vinc = (f" · Trabajado en cambio del {d.cambioDe}" if d.cambioDe else "") + (
            f" · Libre por cambio con el {d.cambioCon}" if d.cambioCon else "")
        info.value = (f"Origen: {fuentes}" if fuentes else "") + vinc
        error.value = ""

    def mover(dias: int) -> None:
        estado["fecha"] += timedelta(days=dias)
        cargar()
        page.update()

    def elegir_fecha(e) -> None:
        if e.control.value:
            estado["fecha"] = e.control.value.date() if hasattr(e.control.value, "date") else e.control.value
            cargar()
            page.update()

    def numero(txt: str, entero: bool = False):
        txt = (txt or "").strip().replace(",", ".")
        if not txt:
            return None
        return int(float(txt)) if entero else float(txt)

    def guardar(_) -> None:
        try:
            ing, sal = w.parse_hora_texto(ingreso.value), w.parse_hora_texto(salida.value)
            extras = []
            for fila in extras_col.controls:
                ini, fin, ref = (c.value for c in fila.controls[:3])
                if ini or fin:
                    extras.append({"inicio": fmt_hms(w.parse_hora_texto(ini)), "fin": fmt_hms(w.parse_hora_texto(fin)),
                                   "ref": (ref or "").strip()})
            previo: Day = estado["day"]
            nuevo = Day(
                fecha=estado["fecha"], ingreso=fmt_hms(ing) if ing is not None else None,
                salida=fmt_hms(sal) if sal is not None else None, tipo=tipo.value or None,
                plan=plan.value or None, antes=previo.antes, objetivoH=numero(objetivo.value),
                colacionMin=numero(colacion.value, True), extras=extras, motivoHE=motivo.value or "",
                nota=nota.value or "", cambioDe=previo.cambioDe, cambioCon=previo.cambioCon,
                avisoCierre=previo.avisoCierre,
            )
        except (ValueError, TypeError) as exc:
            error.value = f"Revisa los datos: {exc}"
            page.update()
            return
        app.svc.guardar_dia_editado(nuevo)
        page.pop_dialog()
        w.snack(page, f"Guardado {w.fecha_corta(nuevo.fecha)}")
        if al_guardar:
            al_guardar()

    selector = ft.DatePicker(first_date=date(2024, 1, 1), last_date=date(2030, 12, 31), on_change=elegir_fecha)
    cargar()
    page.show_dialog(ft.AlertDialog(
        title=ft.Row([
            ft.IconButton(ft.Icons.CHEVRON_LEFT, on_click=lambda _: mover(-1)),
            ft.Container(titulo, expand=True),
            ft.IconButton(ft.Icons.CALENDAR_MONTH, on_click=lambda _: page.show_dialog(selector)),
            ft.IconButton(ft.Icons.CHEVRON_RIGHT, on_click=lambda _: mover(1)),
        ]),
        content=ft.Container(width=460, content=ft.Column(scroll=ft.ScrollMode.AUTO, spacing=10, controls=[
            info, tipo,
            ft.Row([ingreso, salida], wrap=True),
            ft.Row([plan, objetivo, colacion], wrap=True),
            motivo, nota,
            ft.Text("Jornadas extraordinarias (no afectan el saldo)", weight=ft.FontWeight.BOLD),
            extras_col,
            ft.TextButton("Agregar bloque", icon=ft.Icons.ADD,
                          on_click=lambda _: (extras_col.controls.append(fila_extra()), page.update())),
            error,
        ])),
        actions=[ft.TextButton("Cerrar", on_click=lambda _: page.pop_dialog()),
                 ft.FilledButton("Guardar", on_click=guardar)],
    ))
