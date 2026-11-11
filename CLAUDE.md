# Reloj de Jornada — App nativa (Flet) + Motor de sincronización Workera

App personal para registrar la jornada laboral (ingreso, salida, horas extra, compensaciones,
jornadas extraordinarias y monto a cobrar), escrita en **Python + Flet**. Destinos:
**APK Android** (Workera por IMAP o por el Puente Google) y **PWA** (web instalable en iPhone/Android; Workera
vía Puente Google o registro manual). macOS quedó fuera de alcance por decisión del usuario. Las reglas de negocio originales están en
`reloj-de-jornada.md` (fuente de verdad funcional); este archivo las resume y fija las
decisiones técnicas.

## Comandos

```bash
.venv/Scripts/python -m pytest            # Windows (el venv vive en .venv)
python scripts/security_scan.py           # cero credenciales en el código
flet build apk --yes                      # Android local (descarga Flutter/JDK/SDK; compilar fuera de OneDrive)
flet build web --yes                      # PWA local
```

Compilación recomendada: **GitHub Actions** (`.github/workflows/build_release.yml`): tests + escaneo,
APK firmado (secretos `ANDROID_KEYSTORE_BASE64`, `ANDROID_KEYSTORE_PASSWORD`, `ANDROID_KEY_PASSWORD`,
`ANDROID_KEY_ALIAS`) y PWA publicada en GitHub Pages (`--base-url /<repo>/`, rutas hash). Una etiqueta
`vX.Y.Z` crea un Release con el APK. GitHub Pages en repos privados requiere plan pago.
**Firma**: todas las versiones que se repartan deben firmarse con la MISMA clave; si cambia, Android
rechaza la actualización y desinstalar borra los datos locales del usuario.

Skills del proyecto: `/test-workera-parser` y `/build-all` (en `.claude/commands/`).

## Arquitectura

```
src/                     ← raíz de la app para Flet (tool.flet.app.path = "src")
  main.py                ← punto de entrada Flet 1.1.2 (ft.run)
  core/calculator.py     ← reglas de cálculo puras (sin I/O): día, semana, planes, avisos, periodo, valor HE
  data/database.py       ← SQLite local: config, days, workera_events, workera_overrides, imap_seen, meta
  services/workera_parser.py      ← parsea correos Workera Tipo A y Tipo B (solo stdlib)
  services/imap_client.py         ← descarga correos por IMAP SSL 993 (imaplib), solo lectura
  services/attendance_resolver.py ← máquina de estados Entrada/Salida + conciliación con alertas
  services/sync.py       ← IMAP → parser → SQLite → resolver → documento del día
  services/jornada_service.py     ← casos de uso (lo que hacen los botones); la UI solo llama a esto
  services/auth.py       ← credenciales: flet-secure-storage (Android/iOS) o keyring (escritorio)
  services/puente.py     ← cliente del Puente Google (Apps Script, tools/workera_gmail_bridge.gs)
  ui/app.py              ← contenedor: asistente o 3 pestañas, reloj de 1 s, sync cada 15 min
  ui/onboarding.py       ← asistente de primera vez (Gmail, App Password, etiqueta, RUT con «Detectar»)
  ui/hoy_view.py, periodo_view.py, ajustes_view.py, editor_dia.py, widgets.py
tests/                   ← pytest; `pythonpath = ["src"]` en pyproject.toml
scripts/security_scan.py ← detecta credenciales/secretos en el código
```

Vista previa en el navegador (sin tocar el llavero real ni los datos reales):
`RELOJ_WEB_PORT=8550 RELOJ_SECRET_BACKEND=memory FLET_APP_STORAGE_DATA=<carpeta temporal> .venv/Scripts/python src/main.py`
y abrir http://127.0.0.1:8550. En Flet 1.x el modo web exige `view=WEB_BROWSER` + `FLET_FORCE_WEB_SERVER`
(`view=None` levanta un servidor TCP para el cliente de escritorio, no HTTP).

## Varios usuarios (amigos)

- **Una instalación = un usuario.** Cada amigo instala la app en su teléfono/Mac y configura su
  propio Gmail, App Password, etiqueta y RUT en el asistente. No hay servidor ni cuentas compartidas:
  los datos y credenciales nunca salen del dispositivo.
- Nada del dueño está en el código: ni RUT, ni nombre, ni empresa, ni etiqueta obligatoria
  (`02_Reloj_Control` es solo el valor por defecto; con `INBOX` también funciona).
- **Sin RUT configurado no se importa nada**: los correos quedan sin marcar como vistos y el botón
  «Detectar» propone el RUT más frecuente en los correos de Workera de los últimos 30 días.
  Marcas de otro RUT se descartan (útil si alguien recibe copias de correos de colegas).
- Guía para los amigos: `GUIA_AMIGOS.md`.

## Modo PWA (iPhone) — `ui/app.py: MODO_PWA`

- Se activa en Pyodide (`sys.platform == "emscripten"`) o con `RELOJ_SIMULAR_PWA=1` para probar.
- **Sin IMAP**: el navegador no abre sockets, así que no hay Workera automático; el asistente, Hoy y
  Ajustes muestran el modo «Registro manual». No se piden credenciales.
- `main.py` carga `sqlite3` con `pyodide_js.loadPackage` antes de importar la app. La base vive
  en memoria (`Database(":memory:")`) y tras cada escritura (`al_cambiar`, agrupado 1 s) se respalda
  completa en `SharedPreferences` (localStorage) con `exportar()/importar()`.
- `imap_client` importa `ssl` de forma diferida (en Pyodide no está cargado).
- Ícono de la app/PWA: `src/assets/icon.png`.

## Avisos con la app cerrada — `services/push_notifier.py` (ntfy)

- Al cambiar algo que mueve la salida de hoy (ingreso, plan, salida, sync Workera), `RelojApp.actualizar_push`
  programa en ntfy.sh `POST /<canal>/salida-AAAAMMDD` con `At: <unix>` = salida − aviso_salida_min.
  Mismo sequence ID ⇒ reemplaza el programado; `DELETE` lo cancela (al marcar salida o en día libre).
  Solo reenvía si cambió la clave `fecha|salida|minutos|canal` (meta `push_programado`).
- ntfy.sh acepta 10 s – 3 días de anticipación. Si el aviso ya pasó, se cancela.
- Canal aleatorio `reloj-<24 hex>` por usuario (Ajustes → Avisos en el teléfono), el usuario se suscribe
  con la app ntfy (App Store / Google Play). El mensaje solo contiene la hora de salida.
- Transporte: `urllib` en nativo, `pyodide.http.pyfetch` en la PWA.
- Limitación: con la app cerrada no se lee Workera; el aviso se programa cuando el usuario marca
  o abre la app (en Android la sync al abrir lo ajusta a la hora oficial).
- Web Push (VAPID) se descartó: exige servidor propio y duplica ntfy. Netlify y el reenvío de correos a
  `ntfy-<canal>@ntfy.sh` también se descartaron en favor del Puente Google.

## Puente Google (Apps Script) — Workera para iPhone y opcional en Android

- Código: `tools/workera_gmail_bridge.gs` + `tools/appsscript.json` (V8, servicio avanzado Gmail v1,
  scopes: gmail.readonly, script.external_request, script.scriptapp; web app `USER_DEPLOYING` +
  `ANYONE_ANONYMOUS`). Cada usuario lo copia en SU cuenta y ejecuta `setup()` (genera clave en
  Script Properties `TOKEN` e instala el disparador `revisar` cada 10 min).
- API (GET o POST text/plain para evitar preflight CORS; `?accion=…&token=…`): `ping`, `correos`
  (`desde` epoch o `dias`; devuelve RFC 822 en base64url, máx. 400), `config` (canal ntfy, jornada,
  colación, aviso, días), `salida` (la app ya programó el aviso de esa fecha → el puente no lo pisa),
  `respaldo_subir` / `respaldo_bajar` (zlib+base64 en propiedades troceadas de 8 KB, máx. 400 KB).
- **El script NO interpreta**: solo extrae correos; parser y resolver siguen siendo los de Python. La única
  lógica propia es el cálculo simple del aviso en segundo plano (`salidaEstimada_`: primera marca válida
  < 13:00 + jornada + colación; dos marcas ≥ 2 h → cancelar; días libres → nada). Sus funciones puras se
  prueban con node (`tools/bridge.test.js` vía `tests/test_bridge_gs.py`).
- App: `services/puente.py` (`PuenteConfig`, `PuenteGoogle`), `SyncService.sincronizar_puente` /
  `detectar_ruts_puente` (UIDs `g<id>` con cuenta `puente-google`). `RelojApp.fuente()` ∈
  {imap, puente, ninguna} (pref `fuente_workera`; imap no existe en la PWA). URL/clave/RUT del puente:
  almacén seguro en nativo, pref `puente` en la PWA. Tras sincronizar por puente se respalda (máx. 1/h).
- Al programar el aviso, la app llama `informar_salida` y al cambiar ajustes/avisos `enviar_config_puente`.

## Prioridad de fuentes en ingreso/salida (`Day.fuente`)

`manual` (editor del día) > `workera`/`alerta` > `app` (botón «Ahora»). La sincronización nunca pisa
un valor `manual`; sí reemplaza lo marcado con el botón de la app por la hora oficial de Workera.
Una sugerencia aplicada de la alerta queda como `alerta` y no se borra al re-conciliar.
«⇄ Invertir» y «Deshacer mis ajustes» devuelven el control a Workera (`overrides` en SQLite).

- Los imports son relativos a `src/` (`from core.calculator import ...`,
  `from services.workera_parser import ...`) porque Flet empaqueta `src/` como raíz.
- `core` y `services/*_parser|resolver` son **puros** y deterministas: no leen reloj del
  sistema salvo que se les pase (`hoy`, `ahora_s`). Toda la I/O vive en `data/` y `services/imap_client.py`.
- Dependencias mínimas: el parser usa `html.parser` de la stdlib (sin lxml/bs4) para no
  arrastrar extensiones C al build de Android.
- Horas internas = **segundos desde medianoche** (`int`); duraciones = segundos.
  En los documentos se guardan como `"hh:mm:ss"`.

## Reglas de cálculo (de reloj-de-jornada.md)

| Concepto | Regla |
|---|---|
| Jornada normal | 8 h efectivas + 60 min colación (configurables) |
| Salida normal | ingreso + meta + colación |
| Trabajadas | (salida − ingreso) − colación (si salida < ingreso se asume cruce de medianoche) |
| HE del día | trabajadas − meta, si > 0 |
| Faltante del día | meta − trabajadas, si > 0 |
| Saldo | HE − faltantes (día, semana o periodo) |
| Día no laboral (libre, feriado, vacaciones, licencia, permiso, cambio) | meta 0 h; todo lo trabajado es HE **sin descontar colación** |
| Jornadas extraordinarias (`extras`) | bloques aparte `[{inicio, fin, ref}]` (ej. SVR, SVR UDALBA, AAR); **no** afectan el saldo |

- Tipos de día: `laboral` (lun–vie por defecto), `libre` (sáb–dom), `feriado`, `vacaciones`,
  `licencia`, `permiso` (con goce), `cambio` (libre por cambio de día).
- **Cambio de día** (`cambioDe`/`cambioCon`): el día *trabajado* (p. ej. sábado) guarda
  `cambioDe = "<fecha del día libre>"` y pasa a contar como laboral (meta 8 h + colación);
  el día *libre* (p. ej. viernes) queda `tipo = "cambio"` con `cambioCon = "<fecha trabajada>"`.
  Ambos deben estar en la misma semana lun–dom. Se puede deshacer.
- Topes (Ajustes): máx. devolver/compensar por día 2 h; máx. HE por día 2 h; tope de saldo
  10 h por **semana lun–dom** (u opcionalmente por periodo; 0 = sin tope).
- Planes al marcar ingreso (`plan`): `normal`, `comp` (deja la semana en saldo 0, máx. 2 h),
  `adel` (sale `antes` segundos: 30/60/90/120 min; primero usa saldo a favor, el resto queda
  como deuda), `he1`, `he2`, `tope` (solo si lo disponible hasta el tope no es hora exacta).
  Las opciones que superan el tope o el máx. HE diario se muestran **deshabilitadas**.
- Avisos: plan de jornada (al ingresar), deuda pendiente (saldo semanal negativo, "Compensar"
  recomendado), cierre de semana (penúltimo día laboral real ≥ 14:00), último día ("Puedes
  retirarte a las HH:MM:SS"), hora límite del tope, aviso de salida (5 min antes), motivo HE.
  Penúltimo/último día se calculan con los días laborales reales (feriados, permisos, cambios).
- Periodo: **semana lun–dom (por defecto)**, mes calendario, ciclo mensual (ej. 25→24) o fechas
  específicas. Resumen: trabajadas, HE, faltantes, saldo neto, extraordinarias, días trabajados;
  tabla semanal.
- **Mi semana** (`resumen_semana` → `ResumenSemana`): meta, llevas (incluye el día en curso),
  faltan, exceso, HE, faltantes, saldo, días restantes, horas por día y hora de salida de hoy.
  En Hoy aparece como franja «Semana: llevas X de Y · faltan Z» (al tocarla abre Periodo).
- **Ausencias por rango** (`JornadaService.marcar_rango`): vacaciones/licencia/permiso/feriado o
  quitar; solo días laborales; omite días con marcas, días de cambio y (salvo para «feriado»)
  días ya marcados como feriado. Máx. 92 días.
- **Saldo de vacaciones** (`saldo_vacaciones` → `SaldoVacaciones`, en días hábiles): Config
  `vac_saldo_dias` + `vac_saldo_fecha` (lo que informa RR.HH. a una fecha de corte). Se descuentan
  los días `tipo == "vacaciones"` con fecha ≥ corte: `tomados` (≤ hoy) y `programados` (> hoy).
  Opcional `vac_acumular`: suma `vac_dias_anuales / 12` (15 → 1,25) por mes completo desde el
  corte. Los tramos agrupan días separados solo por días libres o feriados. La app **no** conoce los
  feriados de Chile: el usuario debe marcarlos como «Feriado» para que no se descuenten.
- **Valor HE (Chile)**: `sueldo_base ÷ 30 × 28 ÷ (jornada_semanal × 4) × 1,5`, jornada
  semanal por defecto **42 h** (Ley 40 Horas desde abril 2026). $1.500.000 → $12.500/h.
  Monto = saldo neto (si es negativo → $0) × valor HE + horas extraordinarias × su valor.

### Decisiones donde el .md era ambiguo (mantener salvo que el usuario diga otra cosa)
1. El máx. HE diario (2 h) **recorta** la HE de días laborales (`he_s`); el exceso queda en
   `he_bruta_s` para mostrarlo. En días no laborales no se recorta.
2. Un día sin marcas o con solo una marca **no** genera faltante (estado `sin_registro`,
   `en_curso` o `incompleto`); solo los días completos suman al saldo.
3. Con tope por semana, el saldo computable de cada semana es `min(saldo, tope)`; el saldo
   neto del periodo es la suma de los computables (las semanas se recortan al periodo).
4. `comp` es simétrico: si hay saldo a favor sale antes, si hay deuda se queda más (ambos
   ≤ máx. devolver por día).

## Datos (modelo de reloj-de-jornada.md → SQLite)

- `config` → ajustes (una fila JSON por usuario local).
- `days` → un documento por fecha `AAAA-MM-DD` con: `ingreso`, `salida` (hh:mm:ss), `tipo`,
  `plan`, `antes`, `objetivoH`, `colacionMin`, `extras`, `motivoHE`, `nota`, `cambioDe`,
  `cambioCon`, `avisoCierre` (si/no/ok).
- `workera_events` → todo correo procesado: `checksum` (PK de idempotencia), `fecha`, `hora`,
  `tipo_declarado`, `rol_asignado`, `metodo_asignacion`, `raw_text`. Las alertas Tipo B se
  guardan con clave sintética `ALERTA-<fecha>` (la última alerta de un día reemplaza a la anterior).
- Ajustes manuales del usuario sobre marcas Workera se guardan como `overrides` {checksum: rol}
  y el resolver los aplica al final (nunca se pierden al re-sincronizar).

## Correos de Workera

Remitentes: `notificaciones@workera.com` (marcas, Tipo A) e **`info@workera.com` (alertas, Tipo B)**,
confirmado con un correo real. Por eso el filtro IMAP busca por dominio: `FROM "workera.com"`
(`imap_client.criterio_remitente`) sobre
la carpeta/etiqueta configurable (por defecto `02_Reloj_Control`, fallback `INBOX`). Conexión
`imaplib.IMAP4_SSL` puerto 993, `select(readonly=True)` + `BODY.PEEK[]` (no marca leídos).
Fechas IMAP `SINCE` se forman con meses en inglés fijos (no depender del locale).

### Tipo A — "Notificación: Nuevos registros de asistencia - DD/MM/AAAA"
Tablas HTML **Marcación** y **Trabajador**, filas etiqueta | valor:

| Etiqueta | Campo | Formato |
|---|---|---|
| Fecha registro | `fecha` | DD/MM/AAAA → AAAA-MM-DD |
| Hora registro | `hora` | HH:MM:SS |
| Dirección | `direccion` | ej. `Calle Ejemplo 123` |
| Tipo de marcación | `tipo_marca_declarado` | `Entrada` \| `Salida` |
| Dispositivo asociado | `dispositivo` | ej. `RELOJ-01 (SPK0000000001)` |
| Estado registro | `estado` | `Activo` (otras → la marca no se usa en el cálculo) |
| Hash (checksum) | `checksum` | ej. `E7B8C5E7` → ID de idempotencia |
| Nombre completo / RUT | `nombre_trabajador` / `rut_trabajador` | RUT debe coincidir con Ajustes |

### Tipo B — "Alertas de asistencia automáticas - [día] DD/MM/AAAA"
- Tabla Trabajador: `R.U.N.` → `run_trabajador`. Tabla Compañía: `Hora generación alerta`
  (`06/11/2026 20:03:47 (GMT-03:00)`) → `hora_alerta` ISO con offset.
- Regex (sobre texto sin acentos): `Horario:\s*(\d{2}:\d{2})\s*a\s*(\d{2}:\d{2}).*?Fecha:\s*(\d{2}/\d{2}/\d{4})`.
- Alertas: `sobretiempo de (\d+) minutos en el termino de la jornada` (`sobretiempo_fin`),
  `sobretiempo de (\d+) minutos en el inicio` (`sobretiempo_inicio`),
  `(?:atraso|demora|retraso) de (\d+) minutos en el inicio` (`atraso_inicio`),
  `(?:salida anticipada|adelanto) de (\d+) minutos` (`salida_anticipada`).
- Workera **trunca** a minutos: una salida real 17:43:15 se informa como 103 min sobre 16:00.

## Resolución Entrada/Salida (`attendance_resolver.resolver_dia`)

El reloj físico a veces no deja cambiar el botón, así que llegan 2 "Entrada" o 2 "Salida" el
mismo día. **La secuencia cronológica manda sobre la etiqueta del reloj.** Por fecha:

1. Idempotencia por `checksum`; se descartan marcas con `estado` ≠ `Activo`.
2. **Anti-rebote**: una marca a < `debounce_min` (15 min por defecto) de la última marca válida
   se guarda como `rebote` (en `raw_punches`/`workera_events`) y no entra al cálculo.
3. **2 marcas separadas ≥ 2 h**: `ingreso = min`, `salida = max` siempre. Si la etiqueta no
   coincide con el rol → `inferido_por_secuencia = True` y badge
   `"Salida inferida (reloj marcó Entrada)"` / `"Entrada inferida (reloj marcó Salida)"`.
   Entre 15 min y 2 h: se respeta la etiqueta si es Entrada→Salida; si no, min/max + aviso
   `marcas_cercanas_revisar`. **≥ 3 marcas**: primera = ingreso, última = salida, el resto `intermedia`.
4. **1 marca**: < 13:00 → ingreso; 13:00–14:00 → según etiqueta; ≥ 14:00 y `Salida` → salida
   + aviso `falta_entrada`; ≥ 14:00 y `Entrada`: hasta 15:00 → ingreso (turno de tarde),
   > 15:00 → rol `pendiente` + pregunta de 1 clic
   `"Se detectó marca a las HH:MM como 'Entrada'. ¿Es tu Salida de hoy o un turno de tarde?"`
   con acción `⇄ Mover a Salida`.
5. **Conciliación con alerta Tipo B** (`turno_inicio`/`turno_fin` = referencia oficial):
   `salida_reconstruida = turno_fin + sobretiempo_fin` (o `− salida_anticipada`);
   `ingreso_reconstruido = turno_inicio + atraso_inicio` (o `− sobretiempo_inicio`).
   Una marca dentro de `tolerancia_alerta_s` (120 s) de la reconstrucción **confirma** su rol
   con certeza (método `alerta`), aunque el reloj dijera lo contrario, y anula la pregunta
   pendiente. Si falta ingreso o salida se ofrece **sugerencia** de autocompletar (no se aplica
   sola). `jornada_validada` = hay ingreso y salida y todas las reconstrucciones calzan.
   Badge: `"Workera: Turno 07:00-16:00 | +103 min sobretiempo"`.
6. `overrides` manuales (`⇄ Invertir Entrada/Salida`, `⇄ Mover a Salida`) se aplican al final,
   método `manual`.

## Seguridad (obligatorio)

- **Cero credenciales en el código o en tests**: el correo Gmail, la App Password de 16
  caracteres, el RUT y la etiqueta se guardan con `keyring` en escritorio (Keychain de macOS) y con
  `flet-secure-storage` en Android/iOS (Keystore + EncryptedSharedPreferences), porque `keyring`
  no tiene backend en Android. Forzar con `RELOJ_SECRET_BACKEND=memory|keyring|flet`.
  `scripts/security_scan.py` lo verifica y `/build-all` falla si encuentra algo
  (marcar un falso positivo con el comentario `security-scan: ignore`).
- `keyring` es dependencia **solo de desarrollo** (extra `dev`): en Android arrastraría SecretStorage
  y cryptography. La app empaquetada usa `flet-secure-storage`.
- `.gitignore` excluye capturas (`*.png/*.jpg` salvo `src/assets/`) y keystores (`*.jks`).
- OAuth2 de Gmail no se usa: el scope `gmail.readonly` es «restringido» (verificación de Google y
  tokens de 7 días en modo prueba). La App Password + IMAP es lo viable para un grupo de amigos.
- El RUT del usuario **no** va como valor por defecto en el código: se configura en Ajustes.
  Los tests pueden usar RUT de ejemplo.
- IMAP solo lectura; nunca borrar, mover ni marcar correos. Validar remitente
  `@workera.com` y registrar el resultado DKIM de `Authentication-Results` si existe.
- Nunca registrar (log) la App Password ni el cuerpo completo de correos fuera de SQLite local.
