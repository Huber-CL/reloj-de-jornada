"""Pestaña Ajustes: cuenta Workera/Gmail de ESTE dispositivo y reglas de cálculo."""
from __future__ import annotations

from dataclasses import replace

import flet as ft

from core.calculator import Config
from services.attendance_resolver import ResolverConfig
from ui import widgets as w
from ui.onboarding import FormularioCuenta


def _num(campo: ft.TextField, entero: bool = False, opcional: bool = False):
    txt = (campo.value or "").strip().replace(".", "").replace(",", ".") if entero else \
        (campo.value or "").strip().replace(",", ".")
    if not txt:
        if opcional:
            return None
        raise ValueError(f"Falta «{campo.label}»")
    try:
        v = float(txt)
    except ValueError:
        raise ValueError(f"«{campo.label}» debe ser un número") from None
    if v < 0:
        raise ValueError(f"«{campo.label}» no puede ser negativo")
    return int(v) if entero else v


class AjustesView:
    def __init__(self, app):
        self.app = app
        self.page = app.page
        self.lista = ft.ListView(padding=12, spacing=10, expand=True)

    def construir(self) -> ft.Control:
        return self.lista

    def refrescar(self) -> None:
        if self.lista.controls:          # no pisar lo que el usuario está escribiendo
            self._estado_sync.value = self._texto_sync()
            if getattr(self, "_lbl_respaldo", None) is not None:
                self._lbl_respaldo.value, self._lbl_respaldo.color = self._texto_respaldo()
            return
        self.cfg = cfg = self.app.svc.cfg
        rcfg = ResolverConfig(**self.app.db.get_pref("resolver", {}))
        self.form = FormularioCuenta(self.app, self.app.cred)
        self._estado_sync = ft.Text(self._texto_sync(), size=12, color=ft.Colors.ON_SURFACE_VARIANT)

        def txt(v) -> str:
            if v is None:
                return ""
            return str(int(v)) if isinstance(v, float) and v.is_integer() else str(v)

        tf = lambda label, valor, **kw: ft.TextField(label=label, value=txt(valor),  # noqa: E731
                                                     width=kw.pop("width", 170), keyboard_type=ft.KeyboardType.NUMBER,
                                                     dense=True, **kw)
        self.jornada = tf("Jornada diaria (h)", cfg.jornada_h)
        self.colacion = tf("Colación (min)", cfg.colacion_min)
        self.max_dev = tf("Máx. devolver/día (h)", cfg.max_devolver_dia_h)
        self.max_he = tf("Máx. HE/día (h)", cfg.max_he_dia_h)
        self.tope = tf("Tope saldo (h)", cfg.tope_saldo_h, helper="0 = sin tope")
        self.tope_por = ft.Dropdown(label="El tope se cuenta por", value=cfg.tope_por, width=230, dense=True,
                                    options=[ft.DropdownOption(key="semana", text="Semana (lun–dom)"),
                                             ft.DropdownOption(key="periodo", text="Periodo")])
        self.sueldo = tf("Sueldo base ($)", int(cfg.sueldo_base) if cfg.sueldo_base else "")
        self.jsem = tf("Jornada semanal (h)", cfg.jornada_semanal_h)
        self.valor_he = tf("Valor HE manual ($)", cfg.valor_he_manual, hint_text="vacío = calculado")
        self.valor_ext = tf("Valor hora extraordinaria ($)", cfg.valor_hora_extraordinaria, hint_text="opcional")
        self.saldo_neto = ft.Switch(label="Pagar sobre saldo neto", value=cfg.pagar_saldo_neto)
        self.segundos = ft.Switch(label="Mostrar segundos", value=cfg.mostrar_segundos)
        self.aviso = tf("Aviso antes de la salida (min)", cfg.aviso_salida_min)
        self.sonido = ft.Switch(label="Vibrar con el aviso", value=cfg.aviso_sonido)
        self.dias = [ft.Checkbox(label=w.DIAS_CORTOS[i], value=i in cfg.dias_laborales) for i in range(7)]
        self.debounce = tf("Ignorar marcas repetidas a menos de (min)", rcfg.debounce_min, width=260)
        self.error = ft.Text("", color=w.ROJO, size=12)

        valor_calc = self._valor_he_texto(cfg)
        self.lista.controls = [
            self._tarjeta_cuenta(),
            self._tarjeta_push(),
            w.tarjeta(
                ft.Row([self.jornada, self.colacion, self.max_dev, self.max_he, self.tope, self.tope_por], wrap=True),
                ft.Text("Días laborales", size=12),
                ft.Row([ft.Container(c, width=80) for c in self.dias], wrap=True, spacing=0),
                titulo="Jornada y topes", icono=ft.Icons.SCHEDULE,
            ),
            w.tarjeta(
                ft.Row([self.sueldo, self.jsem, self.valor_he, self.valor_ext], wrap=True),
                ft.Text(valor_calc, size=12, color=ft.Colors.ON_SURFACE_VARIANT),
                self.saldo_neto,
                titulo="Valor hora extra (Código del Trabajo, 42 h)", icono=ft.Icons.PAYMENTS,
            ),
            w.tarjeta(ft.Row([self.aviso], wrap=True), self.sonido, self.segundos, self.debounce,
                      titulo="Avisos y pantalla", icono=ft.Icons.NOTIFICATIONS),
            self.error,
            ft.FilledButton("Guardar ajustes", icon=ft.Icons.SAVE, on_click=self._guardar_cfg),
            ft.Container(height=20),
        ]

    def _tarjeta_cuenta(self) -> ft.Control:
        fuente = self.app.fuente()
        opciones = [] if self.app.modo_pwa else [ft.DropdownOption(key="imap", text="Gmail directo (contraseña de aplicación)")]
        opciones += [ft.DropdownOption(key="puente", text="Puente Google (recomendado en iPhone)"),
                     ft.DropdownOption(key="ninguna", text="Sin Workera (marcar a mano)")]
        selector = ft.Dropdown(label="¿Cómo lee la app tus marcas de Workera?", value=fuente, options=opciones,
                               width=380, dense=True)

        def cambiar(e):
            self.app.guardar_fuente(e.control.value)
            self.page.run_task(self.app.enviar_config_puente)
            self._reconstruir()

        selector.on_select = cambiar
        if fuente == "puente":
            cuerpo = self._controles_puente()
        elif fuente == "imap":
            cuerpo = self._controles_imap()
        else:
            cuerpo = [ft.Text("Marca tu ingreso y salida con los botones de la pestaña Hoy.", size=13)]
        return w.tarjeta(selector, *cuerpo, titulo="Conexión con Workera", icono=ft.Icons.MAIL_LOCK)

    def _controles_puente(self) -> list[ft.Control]:
        cfg = self.app.puente_cfg
        self.p_url = ft.TextField(label="URL del Puente (termina en /exec)", value=cfg.url, dense=True,
                                  hint_text="https://script.google.com/macros/s/…/exec")
        self.p_clave = ft.TextField(label="Clave del Puente", value=cfg.clave, password=True,
                                    can_reveal_password=True, dense=True)
        self.p_rut = ft.TextField(label="Tu RUT", value=cfg.rut, hint_text="12.345.678-9", dense=True, expand=True)
        self.p_estado = ft.Text("", size=12)
        error = self.app.db.get_meta("puente_error")
        texto_resp, color_resp = self._texto_respaldo()
        self._lbl_respaldo = ft.Text(texto_resp, size=12, color=color_resp)
        pasos = ("1. Abre el enlace del Puente que te compartieron y toca «Hacer una copia» (o pega el código de "
                 "tools/workera_gmail_bridge.gs en script.google.com).\n"
                 "2. Ejecuta «setup» y acepta los permisos (Google avisa «app no verificada»: es tuya → "
                 "Configuración avanzada → Ir a…).\n"
                 "3. Implementar → Nueva implementación → Aplicación web · Ejecutar como: Yo · Acceso: Cualquier usuario.\n"
                 "4. Pega aquí la URL y la clave que mostró «setup».")
        controles: list[ft.Control] = [
            ft.Text("El Puente corre en TU cuenta de Google: lee tus correos de Workera sin contraseña de "
                    "aplicación, programa el aviso de salida aunque no abras la app y guarda un respaldo.",
                    size=12, color=ft.Colors.ON_SURFACE_VARIANT),
            ft.Text(pasos, size=12),
            self.p_url, self.p_clave,
            ft.Row([self.p_rut, ft.OutlinedButton("Detectar", icon=ft.Icons.SEARCH, on_click=self._detectar_rut_puente)]),
            ft.Row([
                ft.FilledButton("Probar y guardar", icon=ft.Icons.SAVE, on_click=self._guardar_puente),
                ft.OutlinedButton("Sincronizar ahora", icon=ft.Icons.SYNC,
                                  on_click=lambda _: self.page.run_task(self.app.sincronizar)),
            ], wrap=True),
            self.p_estado, self._estado_sync,
            self._lbl_respaldo,
            ft.Row([
                ft.TextButton("Respaldar ahora", icon=ft.Icons.CLOUD_UPLOAD,
                              on_click=lambda _: self.page.run_task(self.app.respaldar)),
                ft.TextButton("Restaurar respaldo", icon=ft.Icons.CLOUD_DOWNLOAD, on_click=self._restaurar),
            ], wrap=True),
        ]
        if error:
            controles.append(ft.Text(f"Último error: {error}", size=12, color=w.ROJO))
        return controles

    def _form_puente(self):
        from services.puente import PuenteConfig
        return PuenteConfig(url=(self.p_url.value or "").strip(), clave=(self.p_clave.value or "").strip(),
                            rut=(self.p_rut.value or "").strip())

    def _msg_puente(self, texto: str, color: str) -> None:
        self.p_estado.value, self.p_estado.color = texto, color
        self.page.update()

    async def _detectar_rut_puente(self, _):
        from services.puente import PuenteError, PuenteGoogle
        cfg = self._form_puente()
        if cfg.errores():
            self._msg_puente(" · ".join(cfg.errores()), w.ROJO)
            return
        self._msg_puente("Buscando tus correos de Workera de los últimos 30 días…", w.AZUL)
        try:
            ruts = await self.app.svc.sync.detectar_ruts_puente(PuenteGoogle(cfg))
        except PuenteError as exc:
            self._msg_puente(str(exc), w.ROJO)
            return
        if not ruts:
            self._msg_puente("El Puente no encontró correos de Workera en tu Gmail (últimos 30 días).", w.AMBAR)
            return
        rut, n = ruts.most_common(1)[0]
        self.p_rut.value = rut
        self._msg_puente(f"Encontré {n} correo(s) del RUT {rut}. Verifica que sea el tuyo.", w.VERDE)

    async def _guardar_puente(self, _):
        from services.puente import PuenteError, PuenteGoogle
        from services.workera_parser import formatear_rut, rut_valido
        cfg = self._form_puente()
        errores = cfg.errores() + ([] if rut_valido(cfg.rut) else ["RUT inválido o vacío (usa Detectar)"])
        if errores:
            self._msg_puente(" · ".join(errores), w.ROJO)
            return
        cfg.rut = formatear_rut(cfg.rut)
        self._msg_puente("Probando el Puente…", w.AZUL)
        try:
            info = await PuenteGoogle(cfg).ping()
        except PuenteError as exc:
            self._msg_puente(str(exc), w.ROJO)
            return
        await self.app.guardar_puente(cfg)
        await self.app.enviar_config_puente()
        self._msg_puente(f"Puente conectado (versión {info.get('version')}).", w.VERDE)
        if info.get("respaldo_fecha") and not self.app.db.get_meta("respaldo_fecha"):
            w.snack(self.page, "Hay un respaldo en tu cuenta de Google: puedes usar «Restaurar respaldo».", w.AZUL)
        await self.app.sincronizar()

    @staticmethod
    def _fecha_local(iso: str) -> str:
        from datetime import datetime
        try:
            return datetime.fromisoformat(iso.replace("Z", "+00:00")).astimezone().strftime("%d-%m-%Y %H:%M")
        except ValueError:
            return iso[:16].replace("T", " ")

    def _texto_respaldo(self) -> tuple[str, str]:
        db = self.app.db
        conflicto, propio = db.get_meta("respaldo_conflicto"), db.get_meta("respaldo_fecha")
        if conflicto:
            return (f"Hay un respaldo más nuevo de otro dispositivo ({self._fecha_local(conflicto)}): no se reemplazó. "
                    "Usa «Restaurar respaldo» para traerlo o «Respaldar ahora» para reemplazarlo con este.", w.AMBAR)
        if propio:
            return f"Último respaldo de este dispositivo: {self._fecha_local(propio)}", ft.Colors.ON_SURFACE_VARIANT
        return "Aún sin respaldo", ft.Colors.ON_SURFACE_VARIANT

    async def _restaurar(self, _):
        from services.puente import PuenteError
        try:
            fecha = await self.app.fecha_respaldo_remoto()
        except PuenteError as exc:
            w.snack(self.page, str(exc), w.ROJO)
            return
        if not fecha:
            w.snack(self.page, "No hay respaldo en tu cuenta de Google todavía.", w.AMBAR)
            return
        dias = self.app.db.contar_dias()
        w.confirmar(self.page, "Restaurar respaldo",
                    f"Respaldo guardado el {self._fecha_local(fecha)}.\n\nSe reemplazarán los datos de este "
                    f"dispositivo ({dias} día(s) registrados) por ese respaldo. No se puede deshacer.",
                    lambda: self.page.run_task(self.app.restaurar_respaldo), "Restaurar", peligro=True)

    def _controles_imap(self) -> list[ft.Control]:
        return [
            ft.Text("Cada persona configura aquí su propio Gmail y RUT. Las credenciales quedan cifradas "
                    f"solo en este dispositivo ({self.app.store.backend.nombre}).", size=12,
                    color=ft.Colors.ON_SURFACE_VARIANT),
            *self.form.controles(),
            ft.Row([
                ft.FilledButton("Probar y guardar", icon=ft.Icons.SAVE, on_click=self._guardar_cuenta),
                ft.OutlinedButton("Sincronizar ahora", icon=ft.Icons.SYNC,
                                  on_click=lambda _: self.page.run_task(self.app.sincronizar)),
            ], wrap=True),
            self._estado_sync,
            ft.Row([
                ft.TextButton("Re-sincronizar todo", icon=ft.Icons.RESTART_ALT, on_click=self._resync_todo),
                ft.TextButton("Quitar mi cuenta de este dispositivo", icon=ft.Icons.LOGOUT,
                              style=ft.ButtonStyle(color=w.ROJO), on_click=self._quitar_cuenta),
            ], wrap=True),
        ]

    def _tarjeta_push(self) -> ft.Control:
        cfg = self.app.push_cfg()
        error = self.app.db.get_meta("push_error")
        activo = ft.Switch(label="Avisar la salida en mi teléfono aunque la app esté cerrada", value=cfg.activo)

        def cambiar(e):
            nuevo = self.app.push_cfg()
            nuevo.activo = bool(e.control.value)
            self.app.guardar_push_cfg(nuevo)
            self._reconstruir()

        activo.on_change = cambiar
        controles: list[ft.Control] = [activo]
        if cfg.activo and cfg.canal:
            controles += [
                ft.Text("1. Instala la app gratuita «ntfy» (App Store o Google Play).", size=13),
                ft.Text("2. En ntfy toca «+» y suscríbete a este canal (servidor ntfy.sh):", size=13),
                ft.Container(ft.Text(cfg.canal, selectable=True, weight=ft.FontWeight.BOLD, size=16),
                             bgcolor=ft.Colors.with_opacity(0.08, w.AZUL), border_radius=8, padding=10),
                ft.Text("3. Toca «Enviar prueba»: debe sonar en el teléfono.", size=13),
                ft.Text("No compartas el canal: quien lo tenga puede ver tus avisos.", size=11, color=w.AMBAR),
                ft.Row([
                    ft.FilledButton("Enviar prueba", icon=ft.Icons.NOTIFICATIONS_ACTIVE,
                                    on_click=lambda _: self.page.run_task(self.app.probar_push)),
                    ft.OutlinedButton("Copiar canal", icon=ft.Icons.COPY, on_click=self._copiar_canal),
                    ft.TextButton("Nuevo canal", icon=ft.Icons.REFRESH, on_click=self._nuevo_canal),
                ], wrap=True),
            ]
            if error:
                controles.append(ft.Text(f"Último error: {error}", size=12, color=w.ROJO))
        return w.tarjeta(*controles, titulo="Avisos en el teléfono (ntfy)", icono=ft.Icons.PHONE_IPHONE)

    async def _copiar_canal(self, _):
        await ft.Clipboard().set(self.app.push_cfg().canal)
        w.snack(self.page, "Canal copiado")

    def _nuevo_canal(self, _):
        def ok():
            cfg = self.app.push_cfg()
            cfg.canal = ""
            self.app.guardar_push_cfg(cfg)
            self._reconstruir()
        w.confirmar(self.page, "Nuevo canal", "Tendrás que suscribirte de nuevo en la app ntfy con el canal nuevo.",
                    ok, "Cambiar")

    def _reconstruir(self) -> None:
        self.lista.controls = []
        self.app.refrescar()

    def _texto_sync(self) -> str:
        ultima = self.app.db.get_meta("ultima_sync")
        estado = "Sincronizando…" if self.app.sincronizando else (
            f"Última sincronización: {ultima.replace('T', ' ')}" if ultima else "Aún no se ha sincronizado")
        extra = (" · el Puente revisa tu Gmail cada 10 min aunque la app esté cerrada" if self.app.fuente() == "puente"
                 else " · se sincroniza al abrir la app y cada 15 min mientras está abierta")
        return estado + extra

    @staticmethod
    def _valor_he_texto(cfg: Config) -> str:
        from core.calculator import valor_hora_extra
        v = valor_hora_extra(cfg)
        return f"Valor HE actual: ${round(v):,}".replace(",", ".") if v else \
            "Fórmula: sueldo ÷ 30 × 28 ÷ (jornada semanal × 4) × 1,5"

    # ------------------------------------------------------------------ acciones
    async def _guardar_cuenta(self, _):
        if await self.form.probar_y_guardar():
            await self.app.sincronizar()

    def _resync_todo(self, _):
        def ok():
            self.app.svc.sync.olvidar_lo_leido()
            self.page.run_task(self.app.sincronizar)
        w.confirmar(self.page, "Re-sincronizar todo",
                    "Se volverán a leer los correos de Workera de los últimos 45 días. Tus ajustes manuales se mantienen.",
                    ok, "Re-sincronizar")

    def _quitar_cuenta(self, _):
        async def borrar():
            await self.app.borrar_credenciales()
            self.lista.controls = []
            self.app.refrescar()
            w.snack(self.page, "Cuenta quitada de este dispositivo. Tus días registrados se mantienen.")
        w.confirmar(self.page, "Quitar cuenta", "Se borrarán de este dispositivo tu Gmail, la contraseña de "
                    "aplicación y el RUT. Los días ya registrados no se borran.",
                    lambda: self.page.run_task(borrar), "Quitar", peligro=True)

    def _guardar_cfg(self, _):
        try:
            dias = tuple(i for i, c in enumerate(self.dias) if c.value)
            if not dias:
                raise ValueError("Elige al menos un día laboral")
            nuevo = replace(
                self.app.svc.cfg,
                jornada_h=_num(self.jornada), colacion_min=_num(self.colacion, True),
                max_devolver_dia_h=_num(self.max_dev), max_he_dia_h=_num(self.max_he), tope_saldo_h=_num(self.tope),
                tope_por=self.tope_por.value, sueldo_base=_num(self.sueldo, True, opcional=True) or 0,
                jornada_semanal_h=_num(self.jsem), valor_he_manual=_num(self.valor_he, True, opcional=True),
                valor_hora_extraordinaria=_num(self.valor_ext, True, opcional=True),
                pagar_saldo_neto=self.saldo_neto.value, mostrar_segundos=self.segundos.value,
                aviso_salida_min=_num(self.aviso, True), aviso_sonido=self.sonido.value, dias_laborales=dias,
            )
            if nuevo.jornada_h <= 0 or nuevo.jornada_semanal_h <= 0:
                raise ValueError("La jornada debe ser mayor que 0")
            debounce = _num(self.debounce, True)
        except ValueError as exc:
            self.error.value = str(exc)
            self.page.update()
            return
        self.error.value = ""
        self.app.svc.guardar_config(nuevo)
        self.page.run_task(self.app.enviar_config_puente)
        self.app.db.set_pref("resolver", {**self.app.db.get_pref("resolver", {}), "debounce_min": debounce})
        self.lista.controls = []          # reconstruir con los valores guardados
        self.app.refrescar()
        w.snack(self.page, "Ajustes guardados", w.VERDE)
