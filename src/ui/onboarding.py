"""Asistente de primera vez: cada persona conecta SU Gmail y SU RUT en su propio teléfono/Mac."""
from __future__ import annotations

import asyncio

import flet as ft

from services.auth import URL_APP_PASSWORDS, Credenciales
from services.imap_client import ImapError
from ui import widgets as w

PASOS_APP_PASSWORD = (
    "1. En tu cuenta de Google activa la Verificación en 2 pasos (si no la tienes).\n"
    "2. Toca el enlace de abajo. En la página de Google escribe un nombre cualquiera (ej. Reloj) "
    "y pulsa Crear. Ese nombre NO va en esta app.\n"
    "3. Google te muestra un recuadro con 16 letras (4 grupos de 4). Cópialas y pégalas en el campo de "
    "abajo. Google no te las vuelve a mostrar."
)


class FormularioCuenta:
    """Campos de la cuenta, usados por el asistente y por Ajustes."""

    def __init__(self, app, cred: Credenciales):
        self.app = app
        self.nombre = ft.TextField(label="Tu nombre (opcional)", value=cred.nombre)
        self.usuario = ft.TextField(label="Tu Gmail", value=cred.usuario, keyboard_type=ft.KeyboardType.EMAIL,
                                    hint_text="nombre@gmail.com")  # security-scan: ignore (texto de ejemplo)
        self.password = ft.TextField(label="Las 16 letras que te dio Google", value=cred.app_password,
                                     password=True, can_reveal_password=True,
                                     hint_text="xxxx xxxx xxxx xxxx",  # security-scan: ignore (formato)
                                     helper="No es tu contraseña de Gmail ni el nombre «Reloj»")
        self.carpeta = ft.TextField(label="Etiqueta de Gmail con los correos de Workera", value=cred.carpeta,
                                    helper="Si no usas etiquetas escribe INBOX")
        self.rut = ft.TextField(label="Tu RUT", value=cred.rut, hint_text="12.345.678-9",
                                helper="Solo se importan las marcas con este RUT")
        self.estado = ft.Text("", size=12)

    def credenciales(self) -> Credenciales:
        return Credenciales(usuario=self.usuario.value or "", app_password=self.password.value or "",
                            rut=self.rut.value or "", carpeta=self.carpeta.value or "",
                            nombre=self.nombre.value or "", remitente=self.app.cred.remitente)

    def controles(self) -> list[ft.Control]:
        return [
            self.nombre, self.usuario,
            ft.Text(PASOS_APP_PASSWORD, size=12, color=ft.Colors.ON_SURFACE_VARIANT),
            ft.TextButton("Abrir Contraseñas de aplicaciones de Google", icon=ft.Icons.OPEN_IN_NEW,
                          on_click=self._abrir_google),
            self.password, self.carpeta,
            ft.Row([ft.Container(self.rut, expand=True),
                    ft.OutlinedButton("Detectar", icon=ft.Icons.SEARCH, on_click=self.detectar_rut)]),
            self.estado,
        ]

    async def _abrir_google(self, _):
        await ft.UrlLauncher().launch_url(URL_APP_PASSWORDS)

    def _msg(self, texto: str, color: str) -> None:
        self.estado.value, self.estado.color = texto, color
        self.app.page.update()

    async def detectar_rut(self, _=None):
        c = self.credenciales()
        errores = [e for e in c.errores() if "RUT" not in e]
        if errores:
            self._msg(" · ".join(errores), w.ROJO)
            return
        self._msg("Buscando tus correos de Workera de los últimos 30 días…", w.AZUL)
        try:
            ruts = await asyncio.to_thread(self.app.svc.sync.detectar_ruts, c)
        except (ImapError, OSError) as exc:
            self._msg(f"No se pudo conectar: {exc}", w.ROJO)
            return
        if not ruts:
            self._msg("No encontré correos de Workera en esa etiqueta. Revisa el nombre o usa INBOX.", w.AMBAR)
            return
        rut, n = ruts.most_common(1)[0]
        self.rut.value = rut
        otros = f" (también aparecen: {', '.join(r for r in ruts if r != rut)})" if len(ruts) > 1 else ""
        self._msg(f"Encontré {n} correo(s) del RUT {rut}{otros}. Verifica que sea el tuyo.", w.VERDE)

    async def probar_y_guardar(self) -> bool:
        c = self.credenciales()
        errores = c.errores()
        if not c.rut:
            errores.append("Falta tu RUT (usa Detectar)")
        if errores:
            self._msg(" · ".join(errores), w.ROJO)
            return False
        self._msg("Probando la conexión con Gmail…", w.AZUL)
        try:
            await asyncio.to_thread(self.app.svc.sync.detectar_ruts, c, 3)
        except (ImapError, OSError) as exc:
            self._msg(f"Gmail rechazó la conexión: {exc}. Revisa el correo y la contraseña de aplicación.", w.ROJO)
            return False
        await self.app.guardar_credenciales(c)
        self._msg("Conexión correcta. Credenciales guardadas de forma segura en este dispositivo.", w.VERDE)
        return True


class Onboarding:
    def __init__(self, app):
        self.app = app
        self.form = FormularioCuenta(app, app.cred)

    def construir(self) -> ft.Control:
        if self.app.modo_pwa:
            return self.construir_pwa()
        return ft.ListView(padding=20, spacing=12, controls=[
            ft.Icon(ft.Icons.TIMER, size=48, color=ft.Colors.PRIMARY),
            ft.Text("Reloj de Jornada", size=26, weight=ft.FontWeight.BOLD),
            ft.Text("Conecta tu Gmail para importar automáticamente tus marcas del reloj Workera. "
                    "Tus datos quedan solo en este dispositivo; nadie más los ve.", size=14),
            *self.form.controles(),
            ft.FilledButton("Probar conexión y continuar", icon=ft.Icons.CHECK, on_click=self._continuar),
            ft.TextButton("Prefiero el Puente Google (sin contraseña de aplicación)", on_click=self._usar_puente),
            ft.TextButton("Configurar más tarde (usar sin Workera)", on_click=self._omitir),
        ])

    def construir_pwa(self) -> ft.Control:
        pasos = (
            "1. Instálala en tu pantalla de inicio: en Safari toca Compartir → «Agregar a inicio» "
            "(en Android: menú ⋮ → «Instalar app»).",
            "2. (Opcional) Si quieres que el aviso de salida suene con la app cerrada, instala la app gratuita «ntfy» "
            "y actívalo en Ajustes → Avisos en el teléfono.",
            "3. Opcional: conecta tus correos de Workera con el «Puente Google» (Ajustes → Conexión con "
            "Workera). Así tus marcas se cargan solas y el aviso suena aunque no abras la app.",
            "4. Sin Puente, marca tu ingreso y salida con los botones de la pestaña Hoy.",
        )
        return ft.ListView(padding=20, spacing=12, controls=[
            ft.Icon(ft.Icons.TIMER, size=48, color=ft.Colors.PRIMARY),
            ft.Text("Reloj de Jornada", size=26, weight=ft.FontWeight.BOLD),
            ft.Text("Tus datos quedan solo en este teléfono; nadie más los ve.", size=14),
            *[ft.Text(p, size=14) for p in pasos],
            ft.FilledButton("Comenzar", icon=ft.Icons.CHECK, on_click=self._omitir),
        ])

    async def _continuar(self, _):
        if await self.form.probar_y_guardar():
            self.app.mostrar_principal()

    def _usar_puente(self, _):
        self.app.guardar_fuente("puente")
        self.app.db.set_meta("onboarding_omitido", "1")
        self.app._indice = 2                        # abrir Ajustes para pegar URL y clave del Puente
        self.app.mostrar_principal()

    def _omitir(self, _):
        self.app.db.set_meta("onboarding_omitido", "1")
        self.app.mostrar_principal()
