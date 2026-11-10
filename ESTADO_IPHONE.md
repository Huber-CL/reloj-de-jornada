# Reloj de Jornada en iPhone (y Android) — estado al 10 de noviembre de 2026

## Resumen
- **iPhone**: la app es una **PWA** (página web instalable con «Agregar a inicio» en Safari). Se
  publicará en **GitHub Pages** con el workflow `.github/workflows/build_release.yml`.
- **Workera en iPhone**: con el **Puente Google** (`tools/workera_gmail_bridge.gs`), un script que cada
  persona copia en su propia cuenta de Google. Lee sus correos de Workera, programa el aviso de salida
  en ntfy aunque la app esté cerrada y guarda un respaldo.
- **Android**: APK con la misma app; para Workera elige **Gmail directo** (lo que ya usas) o el **Puente Google**.

| | Estado |
|---|---|
| PWA compilada y probada en navegador (versión real Pyodide) | ✅ abre, guarda datos al recargar, contacta ntfy |
| Puente Google: código + pruebas de sus funciones (node) | ✅ |
| Puente Google en la app (Ajustes → Conexión con Workera) | ✅ pantalla, validación, sincronización, aviso, respaldo |
| Puente instalado y probado en una cuenta real de Google | ✅ 10-11-2026: `setup` encontró 39 correos de Workera; app 0.1.2 «Puente conectado» |
| Repositorio GitHub + publicación en Pages | ⏳ pendiente |
| Probado en un iPhone real | ⏳ pendiente (después de publicar) |
| APK Android con el Puente (0.1.2) | ⏳ compilando |

## Cómo funciona el Puente Google
```
 Gmail (tu cuenta) ──► Puente (Apps Script, tu cuenta) ──► ntfy.sh ──► aviso en tu teléfono
                            │   cada 10 min: si llegó tu marca de entrada, programa
                            │   «salida = entrada + 8 h + colación − 5 min» (si la app no lo hizo)
                            ▼
                Reloj de Jornada (iPhone/Android)
                  · pide los correos de Workera → mismo motor de la app (doble Entrada/Salida, alertas)
                  · si eliges otro plan, reprograma el aviso y avisa al Puente que no lo pise
                  · sube/baja el respaldo de tus datos
```
- Protegido con una **clave secreta** que genera `setup` (sin ella responde «Clave inválida»).
- Permisos que pide: Gmail **solo lectura**, conexiones externas (ntfy) y disparadores. Nada de Drive.
- Los correos no pasan por terceros: solo la hora de salida va a ntfy.
- Respaldo comprimido guardado en las propiedades del script (tope ~400 KB, sobra para años).
- Límites gratuitos de Google: muy por encima del uso (≈144 revisiones al día de 1–2 s).

## Publicación en GitHub Pages (pendiente, lo hacemos juntos)
1. Crear el repositorio en GitHub (Pages gratis exige **público**; el código no tiene credenciales ni
   RUT reales: los tests usan RUT ficticios).
2. Subir el código. El workflow compila la PWA con la ruta correcta (`/<repo>/`) y la publica en
   `https://<usuario>.github.io/<repo>/`. **No** se sube `dist/` (está en `.gitignore`).
3. En el repositorio: *Settings → Pages → Source: GitHub Actions*.
4. Cada vez que se crea una versión (`vX.Y.Z`) o se ejecuta el workflow a mano: PWA actualizada en
   Pages y APK en *Releases*.

Para el enlace «Hacer una copia» del Puente: crear un proyecto **plantilla aparte** (NO el tuyo, que ya
tiene tu clave en sus propiedades y su disparador) en script.google.com con
`workera_gmail_bridge.gs` + `appsscript.json`, **sin ejecutar `setup`**, y compartirlo como
«Cualquiera con el enlace: lector».
Cada amigo abre ese enlace, entra a **Descripción general** (ícono ⓘ) y toca **Hacer una copia**.
La copia es suya: tu cuenta no ve sus correos ni su clave. (Alternativa: que cada uno pegue el código.)

## Instalar en el iPhone (cada amigo)
1. Abrir el enlace de GitHub Pages en **Safari** → **Compartir → Agregar a inicio** → abrir desde el ícono.
2. Instalar el Puente Google (pasos en `GUIA_AMIGOS.md`, sección 2) y pegar URL + clave en la app.
3. Activar el aviso de salida con **ntfy** (sección 3 de la guía).

## Limitaciones que quedan
- Sin Puente, en iPhone se marca a mano y el aviso solo existe si se abrió la app ese día.
- Si se borra el ícono o los datos de Safari se pierde el registro local → con el Puente se recupera
  con «Restaurar respaldo».
- El aviso automático del Puente asume jornada normal; los planes especiales los aplica la app al abrirse.

## Datos técnicos (para retomar)
- Código del Puente: `tools/workera_gmail_bridge.gs` + `tools/appsscript.json` (servicio avanzado
  Gmail v1, zona America/Santiago). Pruebas: `tools/bridge.test.js` (lo corre `tests/test_bridge_gs.py`).
- Cliente en la app: `src/services/puente.py`; sincronización: `SyncService.sincronizar_puente`.
- Compilar local: en `C:\dev\reloj-jornada` con `TEMP=TMP=C:\dev\tmp` →
  `flet build web --yes ...` o `flet build apk --yes ...` (APK además con
  `JAVA_TOOL_OPTIONS=-Djdk.net.unixdomain.tmpdir=C:\dev\tmp`).
- Simular la PWA en el PC: `RELOJ_SIMULAR_PWA=1 RELOJ_WEB_PORT=8550 .venv/Scripts/python src/main.py`.
- Remitentes Workera: `notificaciones@workera.com` (marcas) e `info@workera.com` (alertas).
- Arquitectura completa en `CLAUDE.md`; guía para amigos en `GUIA_AMIGOS.md`.
