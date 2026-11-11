# Reloj de Jornada en iPhone — paso a paso

Son dos partes: **(A)** instalar la app en el iPhone (2 min) y **(B)** conectar tus correos de Workera
con el «Puente» en tu cuenta de Google (5–10 min, mejor desde un computador).

Tus datos quedan solo en tu iPhone y en tu propia cuenta de Google. Nadie más los ve.

---

## A. Instalar la app en el iPhone

1. Abre **Safari** (tiene que ser Safari) y entra a:
   **https://huber-cl.github.io/reloj-de-jornada/**
2. Espera a que cargue (la primera vez tarda 20–40 segundos).
3. Toca **Compartir** (el cuadrado con flecha hacia arriba, abajo al centro).
4. Desliza hacia abajo → **Agregar a inicio** → **Agregar**.
5. Cierra Safari y abre la app desde el **ícono nuevo** de tu pantalla de inicio.
6. Toca **Comenzar**.

Ya puedes usarla marcando con los botones de la pestaña **Hoy**. Para que tus marcas de Workera se
carguen solas, sigue con la parte B.

---

## B. Conectar Workera con el Puente Google

Hazlo con la cuenta de Google **donde te llegan los correos de Workera**. Es más fácil en un computador
(si solo tienes el iPhone, mira el final).

### B1. Crear tu Puente
1. Entra a **https://script.google.com** → **Nuevo proyecto**.
2. Arriba, donde dice «Proyecto sin título», ponle **Reloj de Jornada - Puente**.
3. En la barra izquierda toca el **engranaje ⚙️ (Configuración del proyecto)** y marca
   **«Mostrar el archivo de manifiesto "appsscript.json" en el editor»**.
4. Vuelve al **Editor** (ícono `< >`).

> Si te enviaron un **enlace a la plantilla del Puente**, en vez de los pasos 1 a 6: abre el enlace →
> ícono **ⓘ Descripción general** → **Hacer una copia**, y sigue en **B2**.

### B1 (cont.). Pegar el código
5. Abre este enlace, selecciona todo el texto (**Ctrl + A**) y cópialo (**Ctrl + C**):
   https://raw.githubusercontent.com/Huber-CL/reloj-de-jornada/main/tools/workera_gmail_bridge.gs
   En el editor abre **Código.gs**, borra todo y pega (**Ctrl + V**).
6. Haz lo mismo con este enlace, pegándolo en el archivo **appsscript.json** (borra lo que tenía):
   https://raw.githubusercontent.com/Huber-CL/reloj-de-jornada/main/tools/appsscript.json
   Guarda con **Ctrl + S**.

### B2. Activarlo
7. En la barra de arriba del código, en el menú de funciones elige **`setup`** y pulsa **▶ Ejecutar**.
8. Google pide permisos:
   - **Revisar permisos** → elige tu cuenta.
   - Aparece **«Google no ha verificado esta aplicación»**: es normal, la app eres tú.
     Toca **Configuración avanzada** → **Ir a Reloj de Jornada - Puente (no seguro)**.
   - Marca **Seleccionar todos** (leer correo *solo lectura*, conectarse a un servicio externo,
     ejecutarse cuando no estás y enviarte un correo **a ti mismo** con la clave) → **Continuar**.
9. Abajo, en el **Registro de ejecución**, aparece:
   - `✓ Puente listo. Correos de Workera en los últimos 30 días: N` (si N es 0, revisa que sea la
     cuenta correcta)
   - `CLAVE para la app (no la compartas): ……`
   - Además te llega un correo **«Reloj de Jornada: clave de tu Puente»** con la clave: desde ahí es más
     fácil copiarla en el iPhone.

### B3. Publicarlo
10. Arriba a la derecha: **Implementar → Nueva implementación**.
11. Junto a «Seleccionar tipo» toca el **engranaje** → **Aplicación web**.
12. **Ejecutar como:** Yo · **Quién tiene acceso:** **Cualquier usuario** → **Implementar**.
13. Copia la **URL de la aplicación web** (empieza con `https://script.google.com/macros/s/` y termina en `/exec`).

### B4. Pegarlo en la app del iPhone
14. Envíate la **URL** y la **clave** al iPhone (por ejemplo en un correo a ti mismo; bórralo después).
15. En la app: pestaña **Ajustes** → **Conexión con Workera** → elige **Puente Google**.
16. Pega la **URL** y la **clave**.
17. Toca **Detectar**: debería aparecer tu RUT. Revisa que sea el tuyo.
18. Toca **Probar y guardar** → debe decir **«Puente conectado (versión 1.0)»**.
19. Ve a la pestaña **Periodo**: deberían aparecer tus días con sus horas.

Desde ahora tus marcas se cargan solas cada vez que abres la app, y se guarda un respaldo en tu
cuenta de Google (si cambias de teléfono: conecta el Puente y toca **Restaurar respaldo**).

---

## C. Uso diario
- **Hoy**: marca ingreso y salida (o deja que el Puente los traiga), elige el plan del día y mira tu hora de
  salida. Arriba verás «Semana: llevas X de Y · faltan Z» (tócalo para ver el detalle).
- **Periodo**: abre en **tu semana** (lun–dom): cuánto llevas, cuánto falta, cuánto toca por día y tu saldo
  de horas extra. Con ‹ › cambias de semana; tocando el título ves el mes completo.
- **Vacaciones, licencia o permiso**: en Periodo → **Vacaciones / licencia** → tipo, desde y hasta →
  **Aplicar**. Esos días no cuentan en la meta. Para deshacer, **Quitar marca**.
- **Ajustes**: tu jornada, días laborales, sueldo base (para estimar el pago de horas extra) y el tope semanal.
- **Actualizaciones**: cuando haya una versión nueva, cierra la app y ábrela otra vez (a veces dos veces).
- **Ícono nuevo**: el iPhone no cambia el ícono de una app ya agregada. Para verlo hay que quitarla y
  agregarla de nuevo, y **eso puede borrar los datos de la app en el iPhone**. Antes:
  1. **Ajustes → Respaldar ahora** (con el Puente conectado) y ten a mano la URL y la clave del Puente
     (la clave está en script.google.com → tu proyecto → ⚙️ Configuración → Propiedades → `TOKEN`;
     la URL en **Implementar → Gestionar implementaciones**).
  2. Mantén presionado el ícono → **Eliminar app** → agrégala otra vez desde Safari.
  3. **Ajustes → Puente Google** → pega URL y clave → **Probar y guardar** → **Restaurar respaldo**.

---

## Si solo tienes el iPhone
Se puede hacer la parte B en el iPhone, pero es más incómodo: en Safari abre script.google.com,
toca **aA** en la barra de direcciones → **Solicitar sitio web de escritorio**, y sigue los mismos pasos
(para copiar el código, mantén presionado el texto → **Seleccionar todo** → **Copiar**).

**Si el iPhone no deja pegar el código** (le pasa a muchos): pide a quien te pasó la app el **enlace a
la plantilla del Puente**. Ábrelo en Safari (con «Solicitar sitio web de escritorio») → ícono
**ⓘ Descripción general** → **Hacer una copia**. Luego, en tu copia, sigue desde **B2** (`setup`): no hay
que pegar nada, la clave te llega por correo y la URL se copia con el botón **Copiar** al implementar.

**Si solo falla `appsscript.json`:** sáltate ese archivo (y el paso 3 del engranaje).
En su lugar, en la barra izquierda del editor toca **Servicios ＋** → elige **Gmail API** → **Agregar**.
Basta con haber pegado **Código.gs**. Al dar permisos, Google puede describir el acceso a Gmail de forma
más amplia, pero el Puente solo lee tus correos de Workera.
(Más fácil aún: pídele a quien te pasó la app el **enlace a la plantilla** y usa «Hacer una copia»: no
hay que pegar nada.)

## Problemas comunes
- **«Clave inválida»**: copia de nuevo la clave del registro de `setup`, sin espacios.
- **«no respondió JSON» o error 401/403**: la implementación debe ser *Aplicación web* con acceso
  **Cualquier usuario**, y la URL debe ser la que termina en `/exec`.
- **No encuentra correos**: el Puente tiene que estar en la cuenta de Google donde llegan los correos
  de Workera.
- **Se ve raro o no carga**: cierra la app (desliza hacia arriba) y ábrela de nuevo; necesita internet.
