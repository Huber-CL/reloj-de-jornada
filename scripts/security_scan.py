"""Escaneo de seguridad: falla (exit 1) si encuentra credenciales en el código.

Uso: python scripts/security_scan.py [ruta_raiz]
Revisa src/, tests/, scripts/ y archivos de configuración del build.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

RAIZ = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).resolve().parent.parent
CARPETAS = ("src", "tests", "scripts")
ARCHIVOS_SUELTOS = ("pyproject.toml", "requirements.txt", ".env")
EXTENSIONES = {".py", ".toml", ".txt", ".json", ".yaml", ".yml", ".cfg", ".ini", ".env"}
IGNORAR = {Path(__file__).resolve()}

REGLAS: list[tuple[str, re.Pattern[str]]] = [
    (
        "asignación de contraseña/secreto con valor literal",
        re.compile(
            r"(?i)\b(pass(word|wd)?|pwd|app_?password|contrase(n|ñ)a|secret|token|api_?key)\b"
            r"\s*[:=]\s*['\"](?!\s*['\"])(?![<*{$])[^'\"\n]{6,}['\"]"
        ),
    ),
    ("App Password de Gmail (xxxx xxxx xxxx xxxx)", re.compile(r"['\"][a-z]{4} [a-z]{4} [a-z]{4} [a-z]{4}['\"]")),
    ("login() con credencial literal", re.compile(r"\.login\(\s*['\"]")),
    ("clave privada", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----")),
    ("cuenta Gmail literal", re.compile(r"[\w.+-]+@gmail\.com", re.I)),
    ("token OAuth de Google", re.compile(r"ya29\.[\w-]{20,}|1//[\w-]{30,}")),
]


def _archivos() -> list[Path]:
    salida: list[Path] = []
    for carpeta in CARPETAS:
        base = RAIZ / carpeta
        if base.is_dir():
            salida += [p for p in base.rglob("*") if p.is_file() and p.suffix.lower() in EXTENSIONES]
    salida += [RAIZ / n for n in ARCHIVOS_SUELTOS if (RAIZ / n).is_file()]
    return [p for p in salida if p.resolve() not in IGNORAR and "__pycache__" not in p.parts]


def _enmascarar(texto: str) -> str:
    return texto if len(texto) <= 6 else texto[:3] + "…" + texto[-2:]


def escanear() -> list[str]:
    hallazgos: list[str] = []
    for ruta in _archivos():
        try:
            lineas = ruta.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            continue
        for n, linea in enumerate(lineas, 1):
            if "security-scan: ignore" in linea:
                continue
            for nombre, patron in REGLAS:
                m = patron.search(linea)
                if m:
                    rel = ruta.relative_to(RAIZ)
                    hallazgos.append(f"{rel}:{n}: {nombre} → {_enmascarar(m.group(0))}")
    return hallazgos


def main() -> int:
    hallazgos = escanear()
    if hallazgos:
        print(f"✗ {len(hallazgos)} posible(s) credencial(es) en el código:")
        print("\n".join("  " + h for h in hallazgos))
        return 1
    print("✓ Cero credenciales en el código.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
