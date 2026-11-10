"""Ejecuta con node las pruebas de las funciones puras del puente Apps Script (tools/*.gs)."""
from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from tests.fixtures.workera_html import html_marcacion, texto_marcacion_plano

RAIZ = Path(__file__).resolve().parent.parent


@pytest.mark.skipif(shutil.which("node") is None, reason="node no está instalado")
def test_funciones_puras_del_puente(tmp_path):
    muestras = {
        "marcacion": html_marcacion(),
        "plano": texto_marcacion_plano(hora="07:00:00"),
        "anulada": html_marcacion(estado="Anulado"),
    }
    archivo = tmp_path / "muestras.json"
    archivo.write_text(json.dumps(muestras), encoding="utf-8")
    r = subprocess.run(["node", str(RAIZ / "tools" / "bridge.test.js"), str(archivo)],
                       capture_output=True, text=True, encoding="utf-8")
    assert r.returncode == 0, r.stderr or r.stdout
    assert "OK puente Apps Script" in r.stdout
