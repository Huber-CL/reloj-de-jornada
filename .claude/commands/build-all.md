---
description: Ejecuta pytest, verifica que no haya credenciales en el código y compila el APK de Android y la PWA (iPhone)
---

Pipeline completo de compilación. Detente en el primer paso que falle y reporta el error.

1. **Tests**: `python -m pytest -q` con el intérprete del venv (`.venv/Scripts/python` en Windows).
   Si algo falla, no compiles.
2. **Seguridad**: `python scripts/security_scan.py`. Debe terminar con código 0
   ("cero credenciales en el código"). Si reporta hallazgos, muéstralos (sin repetir el valor
   del secreto completo) y no compiles.
3. **Compilación**: la vía recomendada es la nube (GitHub Actions, `.github/workflows/build_release.yml`):
   - Si el proyecto está en GitHub y `gh` está disponible, propone lanzar el workflow
     (`gh workflow run build_release.yml`) o crear una etiqueta `vX.Y.Z`; pide confirmación antes de
     empujar etiquetas o commits.
   - Compilación local solo si el usuario lo pide: copiar el proyecto fuera de OneDrive
     (`C:\dev\reloj-jornada`, sin espacios) y ejecutar ahí `flet build apk --yes` y
     `flet build web --yes` (en segundo plano: la primera vez descarga Flutter, JDK y Android SDK).
4. Reporta dónde quedaron los artefactos (`build/apk/*.apk`, `build/web/`, o el Release / GitHub Pages)
   y su tamaño. Recuerda: un APK firmado con clave de depuración sirve para probar, no para repartir.

Nunca agregues credenciales, RUT reales, contraseñas del keystore ni App Passwords a archivos del repo.

$ARGUMENTS
