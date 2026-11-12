# Reloj de Jornada — Guía para configurar tu app

Cada persona usa la app con **sus propios datos**: tus marcas, tu sueldo y tus claves quedan en tu
teléfono y en tu propia cuenta de Google. Nadie más los ve (tampoco quien te pasó la app).

| | iPhone | Android |
|---|---|---|
| Cómo se instala | Enlace web → «Agregar a inicio» en Safari | Archivo `.apk` |
| Marcas de Workera automáticas | ✅ con el **Puente Google** | ✅ con el Puente Google **o** Gmail directo |
| Aviso de salida con la app cerrada (opcional) | ✅ con la app «ntfy» | ✅ con la app «ntfy» |
| Respaldo de tus datos | ✅ en tu cuenta de Google (con el Puente) | ✅ ídem |

---

## 1. Instalar la app

**iPhone**: abre en **Safari** el enlace que te enviaron → **Compartir** (cuadrado con flecha) →
**Agregar a inicio**. Ábrela siempre desde ese ícono y toca **Comenzar**.

**Android**: abre el archivo `.apk` y permite «Instalar apps de origen desconocido» si lo pide. Para
actualizar, instala el `.apk` nuevo encima: tus datos se conservan.

## 2. Conectar Workera con el Puente Google (recomendado, ~5 min, una sola vez)

El Puente es un pequeño programa que corre **en tu propia cuenta de Google** (Apps Script). Lee tus
correos de Workera (`notificaciones@workera.com` y `info@workera.com`) **solo para lectura**, avisa tu
hora de salida aunque no abras la app y guarda un respaldo de tus datos. No necesita tu contraseña.

Hazlo desde un computador (es más cómodo), con la misma cuenta de Google donde te llegan los
correos de Workera:

1. Abre el enlace del Puente que te compartieron y toca **Hacer una copia**.
   *(Alternativa: entra a https://script.google.com → Nuevo proyecto → pega el contenido de
   `workera_gmail_bridge.gs`; en Configuración del proyecto activa «Mostrar el archivo de manifiesto
   appsscript.json» y pega también ese archivo.)*
2. Arriba elige la función **`setup`** y pulsa **Ejecutar**.
3. Google pide permisos y avisa **«Google no verificó esta app»**. Es normal: la app eres tú.
   Toca **Configuración avanzada → Ir a … (no seguro)** → **Permitir**.
   Permisos: leer Gmail (solo lectura), conectarse a ntfy y programar la revisión cada 10 minutos.
4. En el **Registro de ejecución** aparece tu **CLAVE**. Cópiala (no la compartas).
5. Arriba a la derecha: **Implementar → Nueva implementación** → tipo **Aplicación web** →
   *Ejecutar como:* **Yo** · *Quién tiene acceso:* **Cualquier usuario** → **Implementar**.
   Copia la **URL de la aplicación web** (termina en `/exec`).
6. En Reloj de Jornada: **Ajustes → Conexión con Workera → Puente Google**. Pega la **URL** y la
   **clave**, toca **Detectar** para completar tu RUT (revisa que sea el tuyo) y luego **Probar y guardar**.

Listo: la app carga tus marcas (incluso si el reloj marcó dos veces «Entrada»), las alertas diarias y las
marcas que RR.HH. registra cuando se te olvidó marcar (correo «Solicitud de marcación aceptada»).

> **¿Por qué «Cualquier usuario»?** Para que la app pueda consultar el Puente sin iniciar sesión.
> Está protegido con tu clave: sin ella responde «Clave inválida». Si crees que tu clave se filtró,
> ejecuta la función `cambiarClave` y pega la nueva en la app.

### Alternativa solo Android: Gmail directo
En **Ajustes → Conexión con Workera → Gmail directo**:
1. Activa la **Verificación en 2 pasos** en tu cuenta de Google.
2. Entra a https://myaccount.google.com/apppasswords, escribe un nombre (ej. «Reloj») y pulsa **Crear**.
   Ese nombre NO va en la app.
3. Copia las **16 letras** del recuadro y pégalas en la app junto a tu Gmail y la etiqueta (o `INBOX`).
4. **Detectar** → **Probar conexión**.

## 3. (Opcional) Aviso de salida aunque la app esté cerrada
Si no quieres notificaciones, sáltate esta sección: la app funciona igual y el aviso viene desactivado.
1. Instala **ntfy** (App Store o Google Play) y permite sus notificaciones.
2. En Reloj de Jornada: **Ajustes → Avisos en el teléfono** → activa el interruptor.
3. En ntfy toca **+**, escribe el **canal** que muestra la app (servidor `ntfy.sh`) y suscríbete.
4. Toca **Enviar prueba**: el teléfono debe sonar.

Con el **Puente** el aviso se programa solo cuando llega tu marca de entrada (con jornada normal). Si
abres la app y eliges otro plan (+1 HE, salir antes…), la app lo reprograma. Sin Puente, el aviso se
programa cuando marcas o abres la app. **No compartas tu canal** (quien lo tenga ve tus avisos).

## 4. Respaldo de tus datos (con el Puente)
La app guarda una copia en tu cuenta de Google cada hora mientras sincroniza (o con **Respaldar ahora**).
Si cambias de teléfono o borras la app: instálala, conecta el Puente y toca **Restaurar respaldo**.

## 5. Ajustes que conviene revisar
Tu jornada (8 h + colación), días laborales, sueldo base (para estimar el pago de horas extra) y el
tope semanal.

## 6. Vacaciones, licencias y permisos
**Tu saldo de vacaciones.** Pregúntale a RR.HH. cuántos días hábiles de vacaciones tienes disponibles. En
**Periodo → Mis vacaciones → Anotar mi saldo** escribe ese número y la fecha a la que corresponde. Desde ahí
la app descuenta cada día que marques como vacaciones y muestra **Disponibles**, **Tomados** y
**Programados** (los futuros), con la lista de tus tramos. Si RR.HH. te dio el saldo sin contar lo que vas
ganando mes a mes, activa **Sumar lo que voy ganando** (15 días al año = 1,25 por mes; si tienes días
progresivos, cambia los días por año). Cuando RR.HH. te dé un saldo nuevo, solo actualízalo con **Editar saldo**.

**Marcar vacaciones.** En **Mis vacaciones → Tomar vacaciones** eliges las fechas **desde / hasta** (también
futuras). Antes de aplicar, la app te dice cuántos días hábiles descuenta y cuántos te quedarían. Solo se
descuentan los días laborales: los fines de semana, los días con marcas y los días ya marcados como
**Feriado** no se tocan (si hay un feriado en medio, márcalo antes como Feriado).

**Licencia, permiso o feriado.** Botón **Licencia / permiso / feriado**: funciona igual, pero no descuenta
vacaciones. Esos días no cuentan en la meta semanal ni generan faltantes. Para deshacer, elige **Quitar marca**
con las mismas fechas. Un día suelto también se cambia tocándolo en la lista de días (**Tipo de día**).

## Preguntas frecuentes
- **«Clave inválida»**: copia de nuevo la clave del registro de `setup` (sin espacios al inicio o final).
- **«El Puente respondió 401/403» o «no respondió JSON»**: la implementación debe ser *Aplicación web* con
  acceso **Cualquier usuario**, y la URL debe ser la que termina en `/exec` (no la del editor).
- **«No encontró correos de Workera»**: revisa que el Puente esté en la cuenta de Google donde llegan los
  correos de Workera.
- **Cambié algo en el script**: después de editarlo hay que **Implementar → Gestionar implementaciones →
  Editar → Nueva versión** para que la URL use el cambio.
- **No me llegó el aviso**: revisa que «Enviar prueba» suene y que ntfy tenga permiso de notificaciones.
- **Quiero dejar de usarla**: en Ajustes elige «Sin Workera» y desactiva los avisos; en script.google.com
  borra el proyecto del Puente (o en https://myaccount.google.com/permissions quítale el acceso).
