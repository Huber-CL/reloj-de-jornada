"""Credenciales del usuario de ESTE dispositivo (cada amigo configura las suyas en su app).

Guardado:
  - Android / iOS  → flet-secure-storage (Android Keystore + EncryptedSharedPreferences / Keychain)
  - macOS / Windows / Linux → keyring (Keychain de macOS, Administrador de credenciales de Windows)
  - Tests / vista previa → memoria (RELOJ_SECRET_BACKEND=memory)

Nada de esto se escribe en SQLite, en logs ni en el código.
"""
from __future__ import annotations

import asyncio
import os
import re
from dataclasses import dataclass, field
from typing import Optional, Protocol

from services.imap_client import CARPETA_POR_DEFECTO, ImapSettings
from services.workera_parser import WORKERA_SENDER, formatear_rut, rut_valido

SERVICIO = "cl.relojjornada.reloj-jornada"
CLAVES = {
    "usuario": "imap_usuario",
    "app_password": "imap_app_password",
    "rut": "rut_trabajador",
    "carpeta": "imap_carpeta",
    "nombre": "nombre_usuario",
    "remitente": "workera_remitente",
}
URL_APP_PASSWORDS = "https://myaccount.google.com/apppasswords"


@dataclass
class Credenciales:
    usuario: str = ""
    app_password: str = field(default="", repr=False)
    rut: str = ""
    carpeta: str = CARPETA_POR_DEFECTO
    nombre: str = ""
    remitente: str = WORKERA_SENDER

    @property
    def completas(self) -> bool:
        return bool(self.usuario and self.app_password)

    def errores(self) -> list[str]:
        e = []
        if not re.fullmatch(r"[^@\s]+@[^@\s]+\.[a-z]{2,}", self.usuario.strip(), re.I):
            e.append("Correo inválido")
        if not re.fullmatch(r"[a-z]{16}", self.app_password.replace(" ", ""), re.I):
            e.append("La contraseña de aplicación de Google tiene 16 letras (ej. abcd efgh ijkl mnop)")
        if self.rut and not rut_valido(self.rut):
            e.append("RUT inválido (revisa el dígito verificador)")
        if not self.carpeta.strip():
            e.append("Indica la etiqueta/carpeta (o INBOX)")
        return e

    def normalizada(self) -> "Credenciales":
        return Credenciales(
            usuario=self.usuario.strip().lower(), app_password=self.app_password.replace(" ", "").strip(),
            rut=formatear_rut(self.rut) if self.rut else "", carpeta=self.carpeta.strip() or CARPETA_POR_DEFECTO,
            nombre=self.nombre.strip(), remitente=(self.remitente or WORKERA_SENDER).strip().lower(),
        )

    def imap(self) -> ImapSettings:
        return ImapSettings(self.usuario, self.app_password, self.carpeta, self.remitente)


class SecretBackend(Protocol):
    nombre: str

    async def get(self, clave: str) -> Optional[str]: ...
    async def set(self, clave: str, valor: str) -> None: ...
    async def delete(self, clave: str) -> None: ...


class MemoryBackend:
    nombre = "memoria"

    def __init__(self):
        self._datos: dict[str, str] = {}

    async def get(self, clave):
        return self._datos.get(clave)

    async def set(self, clave, valor):
        self._datos[clave] = valor

    async def delete(self, clave):
        self._datos.pop(clave, None)


class KeyringBackend:
    nombre = "keyring"

    def __init__(self, servicio: str = SERVICIO):
        import keyring  # import diferido: no existe backend en Android
        self._kr = keyring
        self._servicio = servicio

    @staticmethod
    def disponible() -> bool:
        try:
            import keyring
            from keyring.backends import fail
            kr = keyring.get_keyring()
            return not isinstance(kr, fail.Keyring) and "null" not in type(kr).__module__.lower()
        except Exception:
            return False

    async def get(self, clave):
        return await asyncio.to_thread(self._kr.get_password, self._servicio, clave)

    async def set(self, clave, valor):
        await asyncio.to_thread(self._kr.set_password, self._servicio, clave, valor)

    async def delete(self, clave):
        try:
            await asyncio.to_thread(self._kr.delete_password, self._servicio, clave)
        except Exception:
            pass


class FletSecureBackend:
    """Debe crearse dentro del contexto de la página Flet (registra el servicio)."""

    nombre = "secure-storage"

    def __init__(self):
        from flet_secure_storage import AndroidOptions, MacOsOptions, SecureStorage
        self._st = SecureStorage(
            android_options=AndroidOptions(shared_preferences_name="reloj_jornada_secure"),
            macos_options=MacOsOptions(account_name=SERVICIO),
        )

    async def get(self, clave):
        return await self._st.get(clave)

    async def set(self, clave, valor):
        await self._st.set(clave, valor)

    async def delete(self, clave):
        await self._st.remove(clave)


def elegir_backend(plataforma: Optional[str]) -> SecretBackend:
    forzado = (os.getenv("RELOJ_SECRET_BACKEND") or "").lower()
    if forzado == "memory":
        return MemoryBackend()
    if forzado == "keyring":
        return KeyringBackend()
    if forzado == "flet":
        return FletSecureBackend()
    if (plataforma or "").lower() in ("android", "android_tv", "ios"):
        return FletSecureBackend()
    if KeyringBackend.disponible():
        return KeyringBackend()
    return FletSecureBackend()


class CredentialStore:
    def __init__(self, backend: SecretBackend):
        self.backend = backend

    async def cargar(self) -> Credenciales:
        valores = {}
        for campo, clave in CLAVES.items():
            valores[campo] = await self.backend.get(clave) or ""
        c = Credenciales(**valores)
        c.carpeta = c.carpeta or CARPETA_POR_DEFECTO
        c.remitente = c.remitente or WORKERA_SENDER
        return c

    async def guardar(self, cred: Credenciales) -> None:
        c = cred.normalizada()
        for campo, clave in CLAVES.items():
            valor = getattr(c, campo)
            if valor:
                await self.backend.set(clave, valor)
            else:
                await self.backend.delete(clave)

    async def borrar(self) -> None:
        for clave in CLAVES.values():
            await self.backend.delete(clave)
