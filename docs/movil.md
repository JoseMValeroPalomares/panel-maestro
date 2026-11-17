# El panel en el móvil

El panel es una PWA: se instala como una app más, abre a pantalla completa en «Hoy» y, en Android, aparece en el menú
**Compartir** de cualquier app (F-2). Para instalarla hace falta abrir el panel por **HTTPS** (ver
[HTTPS.md](HTTPS.md); fuera de casa, [fuera-de-casa.md](fuera-de-casa.md)): por `http://` el navegador no instala
nada ni registra el service worker.

## Android (Chrome)

1. Abre el panel en Chrome con su dirección HTTPS e inicia sesión.
2. Menú **⋮ → Instalar aplicación** (o «Añadir a pantalla de inicio» → Instalar). Aparece «Panel» entre las apps.
3. Prueba a compartir: en cualquier app (YouTube, el navegador, Notas, WhatsApp…) **Compartir → Panel**.
   - Un **enlace** (o un texto que es poco más que un enlace, como comparte YouTube) abre «Guardar en el Baúl» con la
     categoría y «Para más tarde». Si prefieres, «Mejor como tarea o idea» lo pasa a la captura normal.
   - Un **texto** abre la captura rápida ya rellena: tarea, idea o rutina, y los prefijos de siempre funcionan
     (`e: dentista el martes a las 5` es un evento, `r:` una rutina…).
   - Nada se guarda hasta pulsar Guardar. Al guardar vas a Tareas, al Calendario o al Baúl según lo que fuera.
4. Si la sesión había caducado, primero sale el login y, al entrar, vuelves a la captura con lo compartido.

Notas:

- «Panel» solo aparece en Compartir con la app **instalada**; un acceso directo normal no basta.
- Si ya la tenías instalada antes de esta función, Android tarda hasta un día en leer el manifest nuevo. Para no
  esperar: mantén pulsado el icono → Información de la app → Desinstalar, y vuelve a instalarla desde Chrome.
- Firefox y otros navegadores de Android no admiten compartir hacia una PWA: instálala desde Chrome (o Edge/Samsung
  Internet, que también lo admiten).

## iPhone y iPad (Safari)

1. Abre el panel en **Safari** con su dirección HTTPS e inicia sesión.
2. Botón **Compartir → Añadir a pantalla de inicio**. Se abre a pantalla completa, como una app.

**Lo que iOS no permite:** Safari ignora `share_target`, así que **«Panel» no aparece en el menú Compartir de
iPhone ni de iPad** (ningún navegador de iOS lo admite, porque todos usan el motor de Safari). Tampoco hay avisos en
segundo plano del panel en iOS por ahora.

Alternativa con la app **Atajos** (viene con iOS), que sí aparece en Compartir:

1. Atajos → **+** → nombre «Al panel».
2. En los detalles del atajo (ⓘ) activa **Mostrar en la hoja de compartir** y acepta *URL* y *Texto*.
3. Añade la acción **URL** con `https://TU-PANEL/compartir?text=` y, detrás, la variable **Entrada del atajo**
   (Atajos la codifica al usarla en una URL; si no, añade antes «Codificar URL»).
4. Añade la acción **Abrir URL**.

Desde entonces, Compartir → «Al panel» abre `/compartir` en Safari con la captura rellena, igual que en Android
(se abre en Safari, no en la app de la pantalla de inicio: allí la sesión es otra y puede pedirte entrar).

## Sin conexión

Si capturas una tarea, idea o rutina y el panel no contesta (sin cobertura, fuera de casa sin Tailscale, el portátil
apagado), no se pierde: se guarda en el propio móvil («Sin conexión: se guardará al volver») y se manda sola, en orden,
en cuanto el panel vuelve a responder (al abrir cualquier página, al volver a la app o cada minuto). Lo que el panel
rechaza por estar mal escrito no se guarda en la cola: se avisa en el momento. Los eventos (`e:`) que se escriben sin
conexión se guardan sin la confirmación de la fecha; si no se entiende, quedan en el Inbox marcados «Revisar fecha».

## Si algo no va

| Síntoma | Causa probable |
|---|---|
| No sale «Instalar aplicación» | El panel no va por HTTPS, o el certificado no es de confianza en el móvil |
| «Panel» no aparece en Compartir (Android) | La app no está instalada, o se instaló antes de esta función: reinstálala |
| El enlace va como texto | Venía con mucho texto alrededor: elige «Guardar en el Baúl» copiando solo la URL, o guárdalo como tarea |
