# Reloj de Jornada

App personal para registrar la jornada laboral en Chile: ingreso y salida, horas extra con topes
(2 h diarias, 10 h semanales), compensaciones, días no laborales, jornadas extraordinarias y el
valor de la hora extra según el Código del Trabajo (jornada de 42 h).

Lee automáticamente las marcas del reloj control **Workera** desde Gmail, incluso cuando el reloj
marca dos veces «Entrada» o dos veces «Salida».

- **iPhone**: versión web instalable (PWA) publicada en GitHub Pages → Safari → «Agregar a inicio».
- **Android**: APK en la sección *Releases*.
- **Workera**: con el **Puente Google** (`tools/workera_gmail_bridge.gs`), un Apps Script que cada
  persona copia en su propia cuenta de Google. En Android también puede usarse Gmail directo.

Cada persona guarda sus datos en su propio teléfono y en su propia cuenta de Google. No hay servidor
central. Guía de instalación: [GUIA_AMIGOS.md](GUIA_AMIGOS.md).

## Desarrollo
```bash
python -m venv .venv && .venv/Scripts/pip install "flet[all]==1.1.2" flet-secure-storage==1.1.2 keyring pytest
.venv/Scripts/python -m pytest -q
.venv/Scripts/python scripts/security_scan.py
```
Arquitectura y reglas: [CLAUDE.md](CLAUDE.md). Compilación: `.github/workflows/build_release.yml`.
