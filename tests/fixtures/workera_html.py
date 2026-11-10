"""HTML simulado de los correos de Workera (estructura copiada de los correos reales,
con tablas anidadas de maquetación, entidades HTML y &nbsp;). Datos de prueba ficticios."""
from __future__ import annotations

from email.message import EmailMessage
from string import Template

RUT_PRUEBA = "12.345.678-5"          # RUT ficticio (válido) para tests
RUT_OTRO = "20.000.003-K"

_MARCACION = Template("""<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>Workera</title>
<style>td { font-family: Arial; } .x{color:#333}</style></head>
<body>
<table width="100%" cellpadding="0" cellspacing="0"><tr><td align="center">
  <table width="600"><tr><td>
    <img src="https://workera.com/logo.png" alt="workera">
    <h2>Notificaci&oacute;n: Nuevos registros de asistencia.</h2>
    <p>Estimado trabajador:</p>
    <p><b>$nombre</b></p>
    <p>Te informamos que la siguiente marcaci&oacute;n ha sido registrada en los servidores de Workera.</p>
    <table border="1" style="border-collapse:collapse">
      <tr><th colspan="2">Marcaci&oacute;n</th></tr>
      <tr><td><b>Fecha registro</b></td><td>$fecha</td></tr>
      <tr><td><b>Hora registro</b></td><td>$hora</td></tr>
      <tr><td><b>Direcci&oacute;n</b></td><td>Calle Ejemplo&nbsp;123</td></tr>
      <tr><td><b>Tipo de marcaci&oacute;n</b></td><td>$tipo</td></tr>
      <tr><td><b>Dispositivo asociado</b></td><td>RELOJ-01 (SPK0000000001)</td></tr>
      <tr><td><b>Estado registro</b></td><td>$estado</td></tr>
      <tr><td><b>Hash (checksum)</b></td><td>$hash</td></tr>
      <tr><th colspan="2">Trabajador</th></tr>
      <tr><td><b>Nombre completo</b></td><td>$nombre</td></tr>
      <tr><td><b>RUT</b></td><td>$rut</td></tr>
    </table>
  </td></tr></table>
</td></tr></table>
</body></html>""")

_ALERTA = Template("""<html><body>
<table width="100%"><tr><td>
<h2>Alertas de asistencia autom&aacute;ticas - $dia $fecha</h2>
<p>Estimado trabajador</p>
<p>A continuaci&oacute;n se indican las alertas de asistencia con respecto a tu jornada del d&iacute;a.</p>
<table width="100%" style="border:1px solid #000">
  <tr><td colspan="6" style="background:#4a9ede;color:#fff"><b>Trabajador</b></td></tr>
  <tr><td><b>Nombre</b></td><td>$nombre</td><td><b>R.U.N.</b></td><td>$rut</td><td></td><td></td></tr>
  <tr><td colspan="6" style="background:#4a9ede;color:#fff"><b>Compa&ntilde;&iacute;a</b></td></tr>
  <tr><td><b>Nombre</b></td><td>EMPRESA DE PRUEBA LIMITADA</td><td><b>R.U.T.</b></td><td>76.000.000-0</td>
      <td><b>Hora generaci&oacute;n alerta</b></td><td>$fecha $hora_alerta (GMT-03:00)</td></tr>
</table>
<p>Horario: $inicio a $fin ($inicio - $fin). Fecha: $fecha</p>
<ul>$items</ul>
<p>(*) La informaci&oacute;n de alertas enviada corresponde a la procesada a la hora de ejecuci&oacute;n de este correo.</p>
<p>Este correo electr&oacute;nico se ha enviado autom&aacute;ticamente, cumpliendo con la ORD. N&deg;2927/58.</p>
</td></tr></table>
</body></html>""")

ITEM_SOBRETIEMPO_FIN = ('Se registra un <span style="color:#1a9bb5"><b>sobretiempo de {} minutos</b></span> '
                        'en el t&eacute;rmino de la jornada.')
ITEM_ATRASO = 'Se registra un <span><b>atraso de {} minutos</b></span> en el inicio de la jornada.'
ITEM_SALIDA_ANTICIPADA = 'Se registra una <b>salida anticipada de {} minutos</b> en el t&eacute;rmino de la jornada.'


def html_marcacion(fecha="09/11/2026", hora="05:52:47", tipo="Entrada", hash_="E7B8C5E7",
                   rut=RUT_PRUEBA, estado="Activo", nombre="TRABAJADOR DE PRUEBA") -> str:
    return _MARCACION.substitute(fecha=fecha, hora=hora, tipo=tipo, hash=hash_, rut=rut,
                                 estado=estado, nombre=nombre)


def html_alerta(fecha="06/11/2026", dia="viernes", inicio="07:00", fin="16:00",
                items=(ITEM_SOBRETIEMPO_FIN.format(103),), rut=RUT_PRUEBA,
                hora_alerta="20:03:47", nombre="TRABAJADOR DE PRUEBA") -> str:
    lis = "".join(f"<li>{i}</li>" for i in items)
    return _ALERTA.substitute(fecha=fecha, dia=dia, inicio=inicio, fin=fin, items=lis, rut=rut,
                              hora_alerta=hora_alerta, nombre=nombre)


def texto_marcacion_plano(fecha="09/11/2026", hora="05:52:47", tipo="Entrada", hash_="E7B8C5E7",
                          rut=RUT_PRUEBA) -> str:
    return (f"Notificación: Nuevos registros de asistencia.\n\nEstimado trabajador:\n"
            f"Marcación\nFecha registro: {fecha}\nHora registro: {hora}\nDirección: Calle Ejemplo 123\n"
            f"Tipo de marcación: {tipo}\nEstado registro: Activo\nHash (checksum): {hash_}\n"
            f"Trabajador\nRUT: {rut}\n")


def email_bytes(html: str, asunto: str, remitente="Workera <notificaciones@workera.com>",
                auth_results: str | None = None) -> bytes:
    msg = EmailMessage()
    msg["From"] = remitente
    msg["To"] = "usuario@example.com"
    msg["Subject"] = asunto
    msg["Message-ID"] = "<prueba-1@workera.com>"
    if auth_results:
        msg["Authentication-Results"] = auth_results
    msg.set_content("Versión texto del correo")
    msg.add_alternative(html, subtype="html", cte="quoted-printable")
    return msg.as_bytes()
