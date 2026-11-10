# Reloj de Jornada

Web app personal para registrar la jornada laboral: hora de ingreso, hora de salida estimada, horas extra (HE), compensaciones, jornadas extraordinarias y monto estimado a cobrar. Funciona en el navegador o en la app de Claude (iPhone/Mac) y cada usuario tiene su registro privado.

---

## 1. Conceptos y reglas de cálculo

| Concepto | Regla |
|---|---|
| Jornada normal | 8 h efectivas + 60 min de colación (configurable) |
| Salida normal | Ingreso + jornada + colación |
| Horas trabajadas | (Salida − ingreso) − colación |
| Hora extra (HE) del día | Trabajadas − meta del día (si es positivo) |
| Faltante del día | Meta del día − trabajadas (si es positivo) |
| Saldo | HE − faltantes (por día, semana o periodo) |
| Día no laboral (libre, feriado, vacaciones, licencia, permiso, cambio) | Meta 0 h. Todo lo trabajado cuenta como HE, **sin descontar colación** |
| Jornadas extraordinarias | Bloques aparte (ej. SVR, SVR UDALBA, AAR); no afectan el saldo de HE |

### Tipos de día
- **Laboral** (lunes a viernes por defecto)
- **Libre** (sábado y domingo por defecto)
- **Feriado**
- **Vacaciones**
- **Licencia**
- **Permiso con goce**
- **Libre por cambio de día**: un día de semana que no se trabajó porque se recuperó otro día (ej. no trabajar el viernes y trabajar el sábado como jornada normal)

### Topes y límites (configurables en Ajustes)
| Regla | Valor por defecto |
|---|---|
| Máximo a devolver/compensar por día | 2 h |
| Máximo de HE por día | 2 h |
| Tope de saldo acumulado | 10 h por **semana** (lunes a domingo); opcionalmente por periodo |

---

## 2. Flujo diario

1. **Marcar ingreso** (botón "Ahora" o selector tipo carrete con hora, minutos y segundos).
2. La app pregunta **"¿Cómo será tu jornada hoy?"** y muestra la hora de salida de cada opción:
   - **Jornada normal**: 8 h + colación.
   - **Compensar**: deja la semana en saldo cero (devuelve lo que debes o usa lo que tienes a favor), con el máximo de 2 h por día.
   - **Salir antes**: eliges 30 min, 1 h, 1 h 30 o 2 h antes de tu horario normal. Primero se usan las horas a favor; lo que falta queda como deuda que se debe recuperar en los días que quedan de la semana.
   - **+1 HE / +2 HE**: horario normal + 1 o 2 h.
   - **Hasta el tope**: aparece cuando lo disponible para llegar a las 10 h no es una hora exacta.
   - Las opciones que harían superar el tope de saldo aparecen desactivadas.
3. El panel muestra la **hora de salida**, una barra de avance, el tiempo que llevas y el que falta, y el **tope de saldo de la semana** con la **hora límite** para no superarlo.
4. **Aviso de salida** 5 minutos antes (pantalla + sonido), con opción de recordar en 5 min. Solo funciona con la app abierta en pantalla.
5. **Marcar salida**. Si el día quedó con HE, la app pide el **motivo de las horas extra**.

### Días no laborales
Al marcar ingreso en un sábado, domingo o feriado, la app pregunta:
- **Jornada normal (cambio de día)**: se elige qué día de esa semana se recupera; ese día queda como "Libre por cambio de día" y hoy cuenta como jornada normal.
- **Todo como horas extra**: todo el tiempo cuenta como HE, incluida la colación.

El cambio se puede deshacer desde el panel de Hoy.

---

## 3. Avisos automáticos

| Aviso | Cuándo |
|---|---|
| Plan de la jornada | Al marcar el ingreso |
| Deuda pendiente | Días siguientes a un "Salir antes" o con saldo negativo: muestra cuánto debes recuperar y lo sugerido para hoy; "Compensar" aparece como recomendado |
| Cierre de semana | Penúltimo día laboral, desde las 14:00: saldo proyectado y propuesta de compensar mañana (Sí / No) |
| Último día de la semana | Al marcar ingreso: "Puedes retirarte a las HH:MM:SS" para cerrar la semana en cero (Sí / elegir otra opción) |
| Hora límite | Si pasas la hora en que superas el tope de 10 h de saldo |
| Aviso de salida | X minutos antes de la salida estimada (por defecto 5) |
| Motivo de HE | Al marcar una salida que generó HE |

El penúltimo y último día se calculan con los días laborales reales de la semana (consideran feriados, permisos y cambios de día).

---

## 4. Vista del periodo

- **Periodo a contabilizar** (tocar el título del mes):
  - **Mes calendario**
  - **Ciclo mensual** (ej. del 25 al 24)
  - **Fechas específicas** (ej. 25 sep – 28 oct)
- **Resumen**: trabajadas, horas extra, faltantes, saldo neto, jornadas extraordinarias y días trabajados.
- **Estimado a cobrar**: saldo neto de HE × valor hora + jornadas extraordinarias × su valor (opcional). Es un monto bruto.
- **Tabla de HE por semana**: HE, faltantes y saldo de cada semana más el total del periodo.
- **Lista por día**: horario, horas trabajadas, saldo del día y etiquetas (feriado, permiso, cambio de día, motivo HE, jornadas extraordinarias, sin registro).
- **Registrar un día anterior**: abre el primer día sin registro del periodo; desde el editor se puede ir a cualquier fecha.
- **Borrar datos del periodo**: un botón con confirmación (doble toque).

---

## 5. Cálculo del valor hora extra

Fórmula del Código del Trabajo (Chile):

```
Valor HE = sueldo base ÷ 30 × 28 ÷ (jornada semanal × 4) × 1,5
```

- Jornada semanal por defecto: 42 h (Ley 40 Horas, desde abril de 2026).
- Ejemplo: $1.500.000 con 42 h → $12.500 por hora extra.
- El monto se calcula sobre el **saldo neto** (HE − horas devueltas o faltantes); si el saldo es negativo, el monto es $0.

---

## 6. Ajustes

| Ajuste | Por defecto |
|---|---|
| Jornada diaria efectiva | 8 h |
| Colación | 60 min (solo días laborales) |
| Máx. devolver por día | 2 h |
| Máx. HE por día | 2 h |
| Tope de saldo de HE | 10 h (0 = sin tope) |
| El tope se cuenta por | Semana (lun–dom) o periodo |
| Sueldo base y jornada semanal | Para calcular el valor HE |
| Valor hora extra | Calculado o manual |
| Valor hora jornada extraordinaria | Opcional |
| Pagar sobre saldo neto | Activado |
| Mostrar segundos | Activado |
| Aviso antes de la salida | 5 min, con sonido |

---

## 7. Uso compartido y privacidad

- Cada persona necesita su propia cuenta de Claude (la gratuita sirve).
- Se comparte desde el botón **Compartir**, invitando por correo como **Editor** (en plan personal) o **Colaborador** (misma organización). No activar el enlace público.
- Cada usuario ve y edita solo su propio registro y sus ajustes (incluido el sueldo). Nadie, ni el dueño de la app, ve los datos de otro.
- Un Editor puede modificar o republicar la página, pero no acceder a los datos de otros.

---

## 8. Limitaciones

- No envía notificaciones al iPhone: el aviso de salida solo suena con la app abierta en pantalla. En segundo plano se muestra al volver a abrirla (hasta 30 min después de la hora de salida).
- El monto a cobrar es una estimación bruta, antes de descuentos legales, y no aplica redondeos de minutos.

---

## 9. Datos guardados (por usuario)

```
data/users/<id>/config                 → ajustes
data/users/<id>/profile/days/<fecha>   → un documento por día (AAAA-MM-DD)
```

Campos de cada día:

| Campo | Descripción |
|---|---|
| `ingreso`, `salida` | Hora en formato hh:mm:ss |
| `tipo` | laboral, libre, feriado, vacaciones, licencia, permiso, cambio |
| `plan` | normal, comp, adel, he1, he2, tope |
| `antes` | Segundos que sale antes (plan "Salir antes") |
| `objetivoH`, `colacionMin` | Meta y colación propias del día |
| `extras` | Bloques de jornada extraordinaria `[{inicio, fin}]` y `ref` (referencia) |
| `motivoHE`, `nota` | Textos libres |
| `cambioDe` / `cambioCon` | Vínculo entre el día trabajado y el día libre por cambio |
| `avisoCierre` | Respuesta al aviso de cierre de semana (si / no / ok) |
