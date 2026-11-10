"""Diagnóstico: ¿qué correos de Workera ve la app en tu Gmail?

Uso:  .venv/Scripts/python scripts/diagnostico_gmail.py
Pide tu Gmail y la contraseña de aplicación (no se muestra ni se guarda). Solo lee (no marca ni mueve nada).
Imprime: etiquetas parecidas, cuántos correos de Workera hay en cada carpeta y si la app puede leerlos.
"""
from __future__ import annotations

import getpass
import imaplib
import re
import ssl
import sys
from datetime import date, timedelta
from email.header import decode_header, make_header
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
from services.imap_client import fecha_imap  # noqa: E402
from services.workera_parser import WorkeraParseError, parse_email  # noqa: E402

DIAS = 60


def dec(v) -> str:
    try:
        return str(make_header(decode_header(v or "")))
    except Exception:
        return str(v)


def carpetas(conn) -> list[tuple[str, str]]:
    salida = []
    for linea in conn.list()[1] or []:
        txt = linea.decode("utf-8", "replace")
        m = re.match(r'\((?P<flags>[^)]*)\) "[^"]*" (?P<nombre>.+)$', txt)
        if m:
            salida.append((m["flags"], m["nombre"].strip('"')))
    return salida


def revisar(conn, carpeta: str, desde: str) -> None:
    typ, _ = conn.select(f'"{carpeta}"', readonly=True)
    if typ != "OK":
        print(f"  ✗ No se pudo abrir «{carpeta}»")
        return
    _, d1 = conn.uid("SEARCH", None, "FROM", '"workera"', "SINCE", desde)
    _, d2 = conn.uid("SEARCH", None, "SUBJECT", '"asistencia"', "SINCE", desde)
    uids = (d1[0] or b"").split()
    print(f"  «{carpeta}»: {len(uids)} correo(s) con 'workera' en el remitente · "
          f"{len((d2[0] or b'').split())} con 'asistencia' en el asunto (últimos {DIAS} días)")
    for uid in uids[-5:]:
        _, partes = conn.uid("FETCH", uid, "(BODY.PEEK[])")
        raw = next((p[1] for p in partes if isinstance(p, tuple)), b"")
        try:
            c = parse_email(raw)
            if c is None:
                res = "no reconocido como marcación ni alerta"
            else:
                dd = c.datos
                rut = getattr(dd, "rut_trabajador", "") or getattr(dd, "run_trabajador", "")
                extra = f"{dd.hora} {dd.tipo_marca_declarado}" if c.tipo == "A" else f"turno {dd.turno_inicio}-{dd.turno_fin}"
                res = f"OK tipo {c.tipo} · {dd.fecha} {extra} · RUT {rut or '(sin RUT)'} · remitente válido={c.remitente_valido}"
        except WorkeraParseError as exc:
            res = f"ERROR al leer: {exc}"
        import email
        msg = email.message_from_bytes(raw)
        print(f"    - De: {dec(msg['From'])} | Asunto: {dec(msg['Subject'])[:70]}")
        print(f"      → {res}")


def main() -> int:
    usuario = input("Tu Gmail: ").strip()
    clave = getpass.getpass("Contraseña de aplicación (16 letras, no se ve al escribir): ").replace(" ", "")
    etiqueta = input("Etiqueta (Enter = 02_Reloj_Control): ").strip() or "02_Reloj_Control"
    conn = imaplib.IMAP4_SSL("imap.gmail.com", 993, ssl_context=ssl.create_default_context())
    try:
        conn.login(usuario, clave)
    except imaplib.IMAP4.error as exc:
        print(f"✗ Gmail rechazó el ingreso: {exc}")
        return 1
    print("✓ Conectado a Gmail\n")
    todas = carpetas(conn)
    nombres = [n for _, n in todas]
    print(f"Etiqueta «{etiqueta}» existe: {'SÍ' if etiqueta in nombres else 'NO'}")
    parecidas = [n for n in nombres if "reloj" in n.lower() or "workera" in n.lower()]
    if parecidas:
        print("Etiquetas parecidas:", ", ".join(parecidas))
    todos = next((n for f, n in todas if "\\All" in f), None)
    print()
    desde = fecha_imap(date.today() - timedelta(days=DIAS))
    for c in dict.fromkeys([etiqueta if etiqueta in nombres else None, "INBOX", todos]):
        if c:
            revisar(conn, c, desde)
    conn.logout()
    return 0


if __name__ == "__main__":
    sys.exit(main())
