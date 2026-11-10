"""Piezas de UI reutilizables y formato de horas para mostrar."""
from __future__ import annotations

from datetime import date, datetime
from typing import Callable, Optional

import flet as ft

from core.calculator import fmt_duracion, fmt_hms

DIAS = ("lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo")
DIAS_CORTOS = ("lun", "mar", "mié", "jue", "vie", "sáb", "dom")
MESES = ("enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto",
         "septiembre", "octubre", "noviembre", "diciembre")
MESES_CORTOS = ("ene", "feb", "mar", "abr", "may", "jun", "jul", "ago", "sep", "oct", "nov", "dic")

TIPO_ETIQUETA = {
    "laboral": "Laboral", "libre": "Libre", "feriado": "Feriado", "vacaciones": "Vacaciones",
    "licencia": "Licencia", "permiso": "Permiso con goce", "cambio": "Libre por cambio de día",
}
FUENTE_ETIQUETA = {"workera": "Workera", "app": "App", "manual": "Manual", "alerta": "Alerta Workera"}

VERDE = "#2E7D32"
ROJO = "#C62828"
AMBAR = "#EF6C00"
AZUL = "#1565C0"


def ahora_s() -> int:
    n = datetime.now()
    return n.hour * 3600 + n.minute * 60 + n.second


def hora(seg: Optional[int], segundos: bool = True) -> str:
    return "—" if seg is None else fmt_hms(seg, segundos)


def dur(seg: int, segundos: bool = False) -> str:
    return fmt_duracion(seg, segundos)


def dur_signo(seg: int) -> str:
    return ("+" if seg > 0 else "") + fmt_duracion(seg)


def fecha_larga(f: date) -> str:
    return f"{DIAS[f.weekday()].capitalize()} {f.day} de {MESES[f.month - 1]}"


def fecha_corta(f: date) -> str:
    return f"{DIAS_CORTOS[f.weekday()]} {f.day} {MESES_CORTOS[f.month - 1]}"


def chip(texto: str, color: str = AZUL, icono=None) -> ft.Container:
    fila = [ft.Text(texto, size=12, color=color, weight=ft.FontWeight.W_500)]
    if icono:
        fila.insert(0, ft.Icon(icono, size=14, color=color))
    return ft.Container(
        content=ft.Row(fila, spacing=4, tight=True),
        bgcolor=ft.Colors.with_opacity(0.12, color),
        border_radius=12, padding=ft.Padding.symmetric(horizontal=8, vertical=3),
    )


def tarjeta(*controles: ft.Control, titulo: Optional[str] = None, color: Optional[str] = None,
            icono=None) -> ft.Card:
    cuerpo: list[ft.Control] = []
    if titulo:
        cab = [ft.Text(titulo, weight=ft.FontWeight.BOLD, size=15, color=color)]
        if icono:
            cab.insert(0, ft.Icon(icono, color=color, size=18))
        cuerpo.append(ft.Row(cab, spacing=6))
    cuerpo.extend(controles)
    return ft.Card(content=ft.Container(ft.Column(cuerpo, spacing=8), padding=14))


def dato(etiqueta: str, valor: str, color: Optional[str] = None, grande: bool = False) -> ft.Column:
    return ft.Column([
        ft.Text(etiqueta, size=11, color=ft.Colors.ON_SURFACE_VARIANT),
        ft.Text(valor, size=22 if grande else 16, weight=ft.FontWeight.BOLD, color=color),
    ], spacing=0, horizontal_alignment=ft.CrossAxisAlignment.START)


def snack(page: ft.Page, mensaje: str, color: Optional[str] = None) -> None:
    page.show_dialog(ft.SnackBar(ft.Text(mensaje), bgcolor=color, duration=4000))


def selector_hora(page: ft.Page, titulo: str, inicial_s: int, al_elegir: Callable[[int], None]) -> None:
    """Selector tipo carrete con horas, minutos y segundos."""
    valor = {"s": max(0, min(inicial_s, 86399))}
    picker = ft.CupertinoTimerPicker(value=valor["s"], mode=ft.CupertinoTimerPickerMode.HOUR_MINUTE_SECONDS)

    def cambiar(e):
        valor["s"] = int(e.data) if not hasattr(e.data, "hours") else (
            e.data.hours * 3600 + e.data.minutes * 60 + e.data.seconds)

    def aceptar(_):
        page.pop_dialog()
        al_elegir(valor["s"])

    picker.on_change = cambiar
    page.show_dialog(ft.AlertDialog(
        title=ft.Text(titulo),
        content=ft.Container(picker, height=200, width=320),
        actions=[ft.TextButton("Cancelar", on_click=lambda _: page.pop_dialog()),
                 ft.FilledButton("Aceptar", on_click=aceptar)],
    ))


def confirmar(page: ft.Page, titulo: str, texto: str, al_confirmar: Callable[[], None],
              boton: str = "Confirmar", peligro: bool = False) -> None:
    def ok(_):
        page.pop_dialog()
        al_confirmar()

    page.show_dialog(ft.AlertDialog(
        title=ft.Text(titulo), content=ft.Text(texto),
        actions=[ft.TextButton("Cancelar", on_click=lambda _: page.pop_dialog()),
                 ft.FilledButton(boton, on_click=ok,
                                 style=ft.ButtonStyle(bgcolor=ROJO) if peligro else None)],
    ))


def parse_hora_texto(texto: str) -> Optional[int]:
    """'7:5' / '07:05' / '07:05:30' / '' → segundos o None. Lanza ValueError si es inválida."""
    from core.calculator import parse_hms
    t = (texto or "").strip()
    if not t:
        return None
    partes = t.split(":")
    if len(partes) in (2, 3):
        t = ":".join(p.zfill(2) for p in partes)
    return parse_hms(t)
