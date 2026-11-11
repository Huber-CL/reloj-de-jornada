"""Contenedor principal: carga datos y credenciales, muestra el asistente o las 3 pestañas,
corre el reloj (cada segundo), la sincronización Workera y programa los avisos push (ntfy).

Modos:
  - App nativa (APK Android): SQLite en disco, Workera por IMAP, credenciales cifradas.
  - PWA (iPhone/Android desde el navegador, Pyodide): sin IMAP (el navegador no abre sockets),
    base SQLite en memoria respaldada en el almacenamiento local del navegador.
Fuente de Workera (Ajustes): "imap" (Gmail directo, solo app nativa), "puente" (Puente Google en
Apps Script, Android e iPhone) o "ninguna" (registro manual).
"""
from __future__ import annotations

import asyncio
import base64
import os
import sys
import time
from datetime import date
from typing import Optional

import flet as ft

from data.database import Database
from services.auth import CredentialStore, Credenciales, MemoryBackend, elegir_backend
from services.imap_client import ImapError
from services.jornada_service import JornadaService
from services.puente import PuenteConfig, PuenteError, PuenteGoogle, decidir_respaldo_auto
from services.push_notifier import PushConfig, PushError, PushNotifier, generar_canal
from services.sync import ResultadoSync, SyncService
from ui import widgets as w

SYNC_CADA_S = 15 * 60
ES_PYODIDE = sys.platform == "emscripten"
MODO_PWA = ES_PYODIDE or os.getenv("RELOJ_SIMULAR_PWA") == "1"
CLAVE_SNAPSHOT = "reloj_db_snapshot"
RESPALDO_CADA_S = 3600
FUENTES = ("imap", "puente", "ninguna")


class RelojApp:
    def __init__(self, page: ft.Page, db: Optional[Database] = None):
        self.page = page
        self.modo_pwa = MODO_PWA
        self.db = db or Database(":memory:" if ES_PYODIDE else None)
        self.svc = JornadaService(self.db, SyncService(self.db))
        plataforma = page.platform.value if page.platform else None
        self.store = CredentialStore(MemoryBackend() if self.modo_pwa else elegir_backend(plataforma))
        self.cred = Credenciales()
        self.puente_cfg = PuenteConfig()
        self.sincronizando = False
        self._vistas = {}
        self._indice = 0
        self._cuerpo = ft.Container(expand=True)
        self._ultimo_sync_auto = 0.0
        self._guardado_pendiente = False
        self._prefs: Optional[ft.SharedPreferences] = None

    # ------------------------------------------------------------------ arranque
    async def iniciar(self) -> None:
        p = self.page
        p.title = "Reloj de Jornada"
        p.theme = ft.Theme(color_scheme_seed=ft.Colors.TEAL)
        p.dark_theme = ft.Theme(color_scheme_seed=ft.Colors.TEAL)
        p.theme_mode = ft.ThemeMode.SYSTEM
        p.padding = 0
        es_cl = ft.Locale(language_code="es", country_code="CL")     # calendarios y selectores en español
        p.locale_configuration = ft.LocaleConfiguration(supported_locales=[es_cl], current_locale=es_cl)
        if ES_PYODIDE:
            await self._restaurar_snapshot()
        if not self.modo_pwa:
            try:
                self.cred = await self.store.cargar()
            except Exception as exc:              # almacenamiento seguro no disponible
                w.snack(p, f"No se pudieron leer las credenciales: {exc}", w.ROJO)
        await self._cargar_puente()
        primera_vez = not self.db.get_meta("onboarding_omitido")
        if primera_vez and not self.cred.completas and not self.puente_cfg.listo:
            self.mostrar_onboarding()
        else:
            self.mostrar_principal()
        p.run_task(self._bucle)

    async def _restaurar_snapshot(self) -> None:
        self._prefs = ft.SharedPreferences()
        try:
            datos = await self._prefs.get(CLAVE_SNAPSHOT)
            if datos:
                self.db.importar(base64.b64decode(datos))
        except Exception as exc:
            w.snack(self.page, f"No se pudieron cargar tus datos guardados: {exc}", w.ROJO)
        self.db.al_cambiar = self._programar_guardado

    def _programar_guardado(self) -> None:
        if not self._guardado_pendiente:
            self._guardado_pendiente = True
            self.page.run_task(self._guardar_snapshot)

    async def _guardar_snapshot(self) -> None:
        await asyncio.sleep(1)                    # agrupa varias escrituras seguidas
        self._guardado_pendiente = False
        try:
            await self._prefs.set(CLAVE_SNAPSHOT, base64.b64encode(self.db.exportar()).decode("ascii"))
        except Exception as exc:
            print(f"[reloj] no se pudo guardar: {exc}")

    def mostrar_onboarding(self) -> None:
        from ui.onboarding import Onboarding
        self.page.navigation_bar = None
        self.page.controls.clear()
        self.page.add(ft.SafeArea(Onboarding(self).construir(), expand=True))
        self.page.update()

    def mostrar_principal(self) -> None:
        from ui.ajustes_view import AjustesView
        from ui.hoy_view import HoyView
        from ui.periodo_view import PeriodoView
        self._vistas = {0: HoyView(self), 1: PeriodoView(self), 2: AjustesView(self)}
        self.page.navigation_bar = ft.NavigationBar(
            selected_index=self._indice, on_change=self._cambiar_pestana,
            destinations=[
                ft.NavigationBarDestination(icon=ft.Icons.TIMER_OUTLINED, selected_icon=ft.Icons.TIMER, label="Hoy"),
                ft.NavigationBarDestination(icon=ft.Icons.CALENDAR_MONTH_OUTLINED,
                                            selected_icon=ft.Icons.CALENDAR_MONTH, label="Periodo"),
                ft.NavigationBarDestination(icon=ft.Icons.SETTINGS_OUTLINED, selected_icon=ft.Icons.SETTINGS,
                                            label="Ajustes"),
            ],
        )
        self.page.controls.clear()
        self.page.add(ft.SafeArea(self._cuerpo, expand=True))
        self.ir_a(self._indice)
        if self.puede_sincronizar():
            self.page.run_task(self.sincronizar, True)

    def _cambiar_pestana(self, e) -> None:
        self.ir_a(int(e.control.selected_index))

    def ir_a(self, indice: int) -> None:
        self._indice = indice
        if self.page.navigation_bar:
            self.page.navigation_bar.selected_index = indice
        vista = self._vistas[indice]
        self._cuerpo.content = vista.construir()
        vista.refrescar()
        self.page.update()
        self.page.run_task(self.actualizar_push)

    def refrescar(self) -> None:
        if self._vistas:
            self._vistas[self._indice].refrescar()
            self.page.update()
            self.page.run_task(self.actualizar_push)

    # ------------------------------------------------------------------ bucles
    async def _bucle(self) -> None:
        loop = asyncio.get_running_loop()
        while True:
            await asyncio.sleep(1)
            try:
                vista = self._vistas.get(self._indice)
                if vista is not None and hasattr(vista, "tick"):
                    vista.tick()
                if (self.puede_sincronizar() and not self.sincronizando
                        and loop.time() - self._ultimo_sync_auto > SYNC_CADA_S):
                    await self.sincronizar(silencioso=True)
            except Exception as exc:          # el bucle nunca debe morir
                print(f"[reloj] error en bucle: {exc}")

    # ------------------------------------------------------------------ avisos push (ntfy)
    def push_cfg(self) -> PushConfig:
        return PushConfig.from_dict(self.db.get_pref("push"))

    def guardar_push_cfg(self, cfg: PushConfig) -> None:
        if cfg.activo and not cfg.canal:
            cfg.canal = generar_canal()
        self.db.set_pref("push", cfg.to_dict())
        self.db.set_meta("push_programado", None)
        self.page.run_task(self.enviar_config_puente)

    async def actualizar_push(self, forzar: bool = False) -> None:
        """Programa, reprograma o cancela en ntfy el aviso de salida de hoy si cambió algo."""
        cfg = self.push_cfg()
        if not cfg.listo:
            return
        hoy = date.today()
        objetivo = self.svc.objetivo_aviso(hoy)
        minutos = self.svc.cfg.aviso_salida_min
        clave = f"{hoy}|{objetivo}|{minutos}|{cfg.canal}"
        if not forzar and clave == self.db.get_meta("push_programado"):
            return
        self.db.set_meta("push_programado", clave)       # evita envíos duplicados en paralelo
        notifier = PushNotifier(cfg)
        try:
            if objetivo is None:
                await notifier.cancelar_salida(hoy)
            else:
                await notifier.programar_salida(hoy, objetivo, minutos)
            self.db.set_meta("push_error", None)
            if self.fuente() == "puente" and self.puente_cfg.listo:
                await PuenteGoogle(self.puente_cfg).informar_salida(hoy, objetivo)
        except (PushError, PuenteError) as exc:
            self.db.set_meta("push_programado", None)    # reintentar en el próximo refresco
            self.db.set_meta("push_error", str(exc))

    async def probar_push(self) -> None:
        cfg = self.push_cfg()
        if not cfg.listo:
            w.snack(self.page, "Activa los avisos en el teléfono primero.", w.AMBAR)
            return
        try:
            await PushNotifier(cfg).prueba()
            w.snack(self.page, "Aviso de prueba enviado. Debería sonar en tu teléfono.", w.VERDE)
        except PushError as exc:
            w.snack(self.page, str(exc), w.ROJO)

    # ------------------------------------------------------------------ Workera
    def fuente(self) -> str:
        defecto = "ninguna" if self.modo_pwa else "imap"
        f = self.db.get_pref("fuente_workera", defecto)
        return defecto if f not in FUENTES or (f == "imap" and self.modo_pwa) else f

    def guardar_fuente(self, fuente: str) -> None:
        self.db.set_pref("fuente_workera", fuente)
        self._ultimo_sync_auto = 0.0

    def puede_sincronizar(self) -> bool:
        f = self.fuente()
        if f == "imap":
            return self.cred.completas and bool(self.cred.rut)
        if f == "puente":
            return self.puente_cfg.listo and bool(self.puente_cfg.rut)
        return False

    async def sincronizar(self, silencioso: bool = False) -> Optional[ResultadoSync]:
        fuente = self.fuente()
        if fuente == "ninguna":
            return None
        if self.sincronizando:
            if not silencioso:
                w.snack(self.page, "Ya se está sincronizando, espera unos segundos…", w.AZUL)
            return None
        if not self.puede_sincronizar():
            if not silencioso:
                w.snack(self.page, "Completa la conexión con Workera en Ajustes (incluido tu RUT).", w.AMBAR)
            return None
        self.sincronizando = True
        self._ultimo_sync_auto = asyncio.get_running_loop().time()
        self.refrescar()
        try:
            if fuente == "imap":
                res = await asyncio.to_thread(self.svc.sync.sincronizar, self.cred)
            else:
                res = await self.svc.sync.sincronizar_puente(PuenteGoogle(self.puente_cfg), self.puente_cfg.rut)
            if not silencioso or res.marcas_nuevas or res.alertas:
                w.snack(self.page, f"Workera: {res.resumen()}", w.VERDE if not res.errores else w.AMBAR)
            if fuente == "puente":
                await self.respaldar(manual=False)
            return res
        except (ImapError, PuenteError, OSError, ValueError) as exc:
            if not silencioso:
                w.snack(self.page, f"No se pudo sincronizar: {exc}", w.ROJO)
            return None
        finally:
            self.sincronizando = False
            self.refrescar()

    # ------------------------------------------------------------------ Puente Google
    async def _cargar_puente(self) -> None:
        if self.modo_pwa:
            self.puente_cfg = PuenteConfig.from_dict(self.db.get_pref("puente"))
            return
        try:
            b = self.store.backend
            self.puente_cfg = PuenteConfig(url=await b.get("puente_url") or "",
                                           clave=await b.get("puente_clave") or "",
                                           rut=await b.get("puente_rut") or self.cred.rut)
        except Exception:
            self.puente_cfg = PuenteConfig()

    async def guardar_puente(self, cfg: PuenteConfig) -> None:
        if self.modo_pwa:
            self.db.set_pref("puente", cfg.to_dict())
        else:
            b = self.store.backend
            for clave, valor in (("puente_url", cfg.url), ("puente_clave", cfg.clave), ("puente_rut", cfg.rut)):
                if valor:
                    await b.set(clave, valor)
                else:
                    await b.delete(clave)
        self.puente_cfg = cfg
        # Quien guarda sincroniza enseguida: marcarlo como reciente evita que el bucle lance
        # una segunda sincronización en paralelo (la que daba «0 marcas nuevas»).
        self._ultimo_sync_auto = asyncio.get_running_loop().time()

    async def enviar_config_puente(self) -> None:
        """Pasa al puente lo que necesita para el aviso en segundo plano (canal ntfy, jornada, días)."""
        if self.fuente() != "puente" or not self.puente_cfg.listo:
            return
        try:
            await PuenteGoogle(self.puente_cfg).configurar(self.push_cfg(), self.svc.cfg)
            self.db.set_meta("puente_error", None)
        except PuenteError as exc:
            self.db.set_meta("puente_error", str(exc))

    async def respaldar(self, manual: bool = True) -> None:
        """Sube el respaldo. El automático (máx. 1/h) no pisa un respaldo más nuevo de otro
        dispositivo ni sube una base vacía; el manual («Respaldar ahora») siempre sube."""
        if not self.puente_cfg.listo:
            return
        puente = PuenteGoogle(self.puente_cfg)
        try:
            if not manual:
                ultimo = float(self.db.get_meta("respaldo_ts") or 0)
                if time.time() - ultimo < RESPALDO_CADA_S:
                    return
                remoto = (await puente.ping()).get("respaldo_fecha")
                decision = decidir_respaldo_auto(self.db.get_meta("respaldo_fecha"), remoto, self.db.contar_dias())
                if decision == "conflicto":
                    self.db.set_meta("respaldo_conflicto", remoto)
                if decision != "subir":
                    return
            fecha = await puente.subir_respaldo(self.db.exportar())
            self.db.set_meta("respaldo_ts", str(time.time()))
            self.db.set_meta("respaldo_fecha", fecha)
            self.db.set_meta("respaldo_conflicto", None)
            if manual:
                w.snack(self.page, "Respaldo guardado en tu cuenta de Google.", w.VERDE)
        except PuenteError as exc:
            if manual:
                w.snack(self.page, str(exc), w.ROJO)
        finally:
            if manual:
                self.refrescar()

    async def fecha_respaldo_remoto(self) -> Optional[str]:
        return (await PuenteGoogle(self.puente_cfg).ping()).get("respaldo_fecha")

    async def restaurar_respaldo(self) -> None:
        try:
            datos, fecha = await PuenteGoogle(self.puente_cfg).bajar_respaldo()
        except PuenteError as exc:
            w.snack(self.page, str(exc), w.ROJO)
            return
        if not datos:
            w.snack(self.page, "No hay respaldo en tu cuenta de Google todavía.", w.AMBAR)
            return
        self.db.importar(datos)
        self.db.set_meta("respaldo_fecha", fecha)      # este dispositivo queda al día con el respaldo
        self.db.set_meta("respaldo_conflicto", None)
        if ES_PYODIDE:
            self._programar_guardado()
        w.snack(self.page, f"Datos restaurados (respaldo del {str(fecha)[:10]}).", w.VERDE)
        self.mostrar_principal()

    async def guardar_credenciales(self, cred: Credenciales) -> None:
        await self.store.guardar(cred)
        self.cred = await self.store.cargar()

    async def borrar_credenciales(self) -> None:
        await self.store.borrar()
        self.cred = Credenciales()

    def hoy(self) -> date:
        return date.today()
