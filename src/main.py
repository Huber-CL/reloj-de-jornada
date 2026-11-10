"""Punto de entrada de Reloj de Jornada (Flet 1.1.2).

Desarrollo:    python src/main.py                         (ventana de escritorio)
Vista web:     RELOJ_WEB_PORT=8550 python src/main.py     (servidor local, sin abrir navegador)
Simular PWA:   RELOJ_SIMULAR_PWA=1 RELOJ_WEB_PORT=8550 python src/main.py
Compilar:      flet build apk   /   flet build web (PWA para iPhone)
"""
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import flet as ft  # noqa: E402


async def main(page: ft.Page) -> None:
    if sys.platform == "emscripten":
        # En la PWA (Pyodide) sqlite3 puede venir incluido o como paquete aparte según la versión.
        try:
            import sqlite3  # noqa: F401
        except ImportError:
            import pyodide_js  # type: ignore[import-not-found]
            await pyodide_js.loadPackage("sqlite3")
    from ui.app import RelojApp
    await RelojApp(page).iniciar()


if __name__ == "__main__":
    puerto = os.getenv("RELOJ_WEB_PORT")
    if puerto:
        os.environ.setdefault("FLET_FORCE_WEB_SERVER", "true")   # servir sin abrir el navegador
        ft.run(main, view=ft.AppView.WEB_BROWSER, port=int(puerto), host="127.0.0.1")
    else:
        ft.run(main)
