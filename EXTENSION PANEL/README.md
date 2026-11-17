# Extensión de Firefox: Panel · Inbox, Baúl y agenda

Envía al **Inbox** del Panel lo que seleccionas o la página que ves (tarea o idea, con categoría y prioridad, o como
paso de otra), guarda enlaces y vídeos en el **Baúl** y consulta y gestiona tu **agenda** (ver, crear, pasar a mañana y
completar). Si el Panel no responde, lo guarda en una cola y lo envía solo en cuanto vuelve la conexión.

Está hecha para **Firefox** (Manifest V2, API `browser.*`). Sus atajos de teclado solo funcionan con Firefox en primer
plano; para capturar desde cualquier sitio del escritorio está `Super+K` (ver docs/escritorio.md).

## Instalar

1. En el servidor, crea un token (no cambia tu contraseña; el token anterior deja de valer):
   `python -m scripts.set_password --solo-token` y reinicia `uvicorn`.
2. Empaqueta: `python -m scripts.build_extension` → `dist/panel-firefox-<versión>.xpi`.
3. Firefox normal solo instala complementos **firmados**:
   - **Para siempre**: súbelo en <https://addons.mozilla.org/developers/> como **«En tu propio sitio» (no listado)**;
     te devuelven el `.xpi` firmado sin publicarlo. Se instala arrastrándolo a Firefox.
   - **Para probar**: `about:debugging` → «Este Firefox» → «Cargar complemento temporal…» → `manifest.json`
     (se quita al cerrar Firefox).
   - Firefox Developer Edition / Nightly: `xpinstall.signatures.required = false` en `about:config` y abrir el `.xpi`.
4. Se abre la página de opciones: pulsa **Detectar** (o escribe la dirección del Panel, la misma que en el
   navegador), pon el token, **Probar conexión** y **Guardar**.

**La dirección no se escribe a mano ni se queda vieja (2.11)**. Se guarda en el almacenamiento de la extensión, no en
el código, y:

- **Detectar** prueba, por orden, las direcciones que el propio Panel dijo en su último latido (la primera es la
  recomendada: el nombre `https://…ts.net` de la tailnet, que no cambia aunque cambien las IP), este equipo
  (`127.0.0.1:8000`) y la reserva DHCP del servidor (`192.168.1.50:8000`). Vale la que contesta a `/healthz` con
  `app: panel-maestro`. Firefox pide permiso para esas direcciones en un solo aviso.
- Tras conectar, la extensión manda un **latido** (`POST /api/red/latido`, también al arrancar y cada 30 min): el Panel
  la enseña en Ajustes → «Red y dispositivos» (versión, por dónde entra, última vez) y avisa si entra por una
  dirección que ya no es suya. Si el Panel recomienda otra dirección (https), las opciones la ofrecen con un clic.
- Si la dirección guardada deja de contestar, la extensión **cambia sola** a otra de las del último latido, pero solo
  a una `https` o de este mismo equipo y con permiso ya dado. A una IP `http` de la red local no cambia sin que la
  confirmes con «Detectar»: en otra wifi esa IP podría ser de otro aparato y se llevaría el token.

**Permisos (desde la 2.9)**: la extensión ya no tiene acceso fijo a ninguna web. Al pulsar **Guardar** (o **Probar
conexión**) en las opciones, Firefox pide permiso solo para la dirección del Panel; YouTube solo se pide si activas sus
funciones (o con «Permitir en YouTube»). Al actualizar desde la 2.8 se abren las opciones: pulsa **Guardar** una vez y
acepta el aviso. Hasta entonces el popup dice «Falta el permiso».

**Entrar sin escribir la contraseña** (desde la 2.9, sin contraseña): cuando caduca la sesión y abres la pantalla de
acceso (`/login`) de la dirección configurada, la extensión entra con su token (`POST /api/ext/sesion` devuelve la
cookie de sesión) y te lleva a la página que pedías. **La contraseña del Panel no se guarda en ningún sitio**: la que
guardaban las versiones 2.3–2.8 se borra al actualizar. Se desactiva con «Entrar solo cuando caduque la sesión del
Panel». Si el Panel muestra un aviso (o el token no vale) no lo reintenta.

Al actualizar desde la versión 1.x se conserva la dirección guardada; solo hay que añadir el token.

## Usar

| Qué | Cómo |
|---|---|
| Enviar al Inbox | Botón de la barra o `Alt+Mayús+I`. Con texto seleccionado, ya viene escrito |
| Dónde va (2.8) | En el Inbox y en el Baúl: **Puntual**, **Universidad** (o una asignatura) o **Proyectos** (o un proyecto). Se recuerda la última elección y la lista se guarda para usarla sin conexión. En el texto también valen las menciones del Panel: `@gabd`, `#panel-maestro v0.3`; si una no existe, avisa y no guarda nada |
| Guardar en el Baúl | Es la **primera pestaña** y la que se abre siempre (2.7; con texto seleccionado se abre el Inbox). También `Alt+Mayús+B` |
| Clasificación automática del Baúl (2.7) | El selector «Normal / Más tarde / Visto» está plegado: una insignia dice qué ha detectado y por qué, y «Cambiar» lo despliega. **Canal** (`/@usuario`, `/channel/`, `/c/`, `/user/`) → se guarda como canal de YouTube. **Vídeo que ya está en el Baúl**, o con el % reproducido por encima del umbral de Opciones (50 % por defecto) → «Visto» (si ya estaba, lo marca sin duplicarlo). **Vídeo nuevo** → «Ver más tarde». Si no está seguro (sin conexión, una página de YouTube que no es vídeo ni canal) usa «Ver más tarde», con «?» en la insignia. Las webs que no son de YouTube no se clasifican |
| Categoría automática del Baúl (2.10) | La propone el Panel y se ve igual que la clasificación: insignia con la categoría y el motivo, y «Cambiar» para abrir el campo y los chips (las últimas usadas y las del Baúl, en su orden). Por orden: **el enlace ya está** en el Baúl → su categoría; **vídeo de un canal guardado** (o con otros vídeos de ese canal) → la suya; **otras páginas de la misma web** → la más repetida; **palabras del título** (el nombre de una categoría, las subcategorías de tus notas o dos palabras de lo que ya tiene) → propuesta con «?». Sin pistas, el selector se abre solo y, si no eliges, va a «General». Lo que eliges a mano no lo pisa la detección. Sin conexión, la última usada |
| Duplicados (2.7) | Un vídeo se identifica por su **ID**: `watch?v=…&list=…`, `youtu.be/…`, `shorts/…`, `live/…` y `embed/…` son el mismo, y se guarda siempre como `https://www.youtube.com/watch?v=ID` |
| Envío rápido (sin popup) | Clic derecho sobre texto seleccionado o un enlace → «Enviar … al Inbox ya»: llega como tarea y un aviso del sistema lo confirma (o avisa de que quedó en la cola) |
| Desde la página | Clic derecho: «Enviar … al Inbox…» (abre el popup), «Enviar esta página al Inbox», «Guardar el enlace / esta página en el Baúl» |
| Prioridad y categoría | Prioridad en un clic (flechas para moverse); las últimas categorías usadas, y después las del Panel, salen como chips bajo el campo |
| Paso de otra tarea o idea (2.5) | En el Inbox del popup, «Paso de»: elige una tarea o idea existente (del mismo tipo) y lo que escribas se crea como su paso |
| Prefijos (2.5) | Igual que en el Panel y el escritorio: `t:` tarea, `i:` idea, `r:` rutina («r: gimnasio lunes y jueves a las 19»), `e:` evento en lenguaje natural («e: dentista mañana 17:00»; si la fecha no se entiende, va al Inbox con «Revisar fecha») |
| Agenda (2.5) | Pestaña «Agenda» o `Alt+Mayús+A`: los próximos 7 días (eventos, tareas con fecha y rutinas); el círculo completa una tarea o la rutina de ese día, la flecha la pasa a mañana (conserva la hora). Arriba, «Nuevo evento» en lenguaje natural con vista previa antes de crearlo. Sin conexión muestra la última agenda guardada y los eventos nuevos van a la cola |
| Baúl: estado y canal (2.6.1) | «Guardar como»: Normal, Más tarde o Visto. En un vídeo de YouTube avisa si su canal está en el Baúl y, si no, lo añade con un botón. «Paso de…» está plegado en el Inbox |
| YouTube (2.6) | Si ves un vídeo de un canal guardado en el Baúl, se marca como visto al reproducir la mitad (ajustable en Opciones; si no estaba en el Baúl, se añade ya como visto). En la página de ese canal, los vídeos vistos salen atenuados con «✓ Visto». Los demás canales no se envían al Panel |
| Enviar | `Ctrl+Intro` |

**Tema**: en las opciones, los mismos 9 temas que el Panel (Catppuccin Mocha por defecto). Se aplica al popup y a las
opciones; se guarda en este Firefox.

Insignia del icono: número de pendientes del Inbox · `↑N` envíos en cola · `×` sin conexión · `!` falta configurar
o token no válido. Se actualiza cada minuto y la cola se reintenta a la vez.

## Archivos

- `manifest.json` — Manifest V2 (API `browser.*` de Firefox). Mismo id que la versión anterior.
- `lib/panel.js` — configuración, peticiones con `Authorization: Bearer`, cola sin conexión (común).
- `background.js` — menús contextuales (con el envío rápido y su notificación), atajos, insignia y reintentos.
- `youtube.js`, `youtube.css` — content script de youtube.com: marca vistos y pinta las miniaturas (las peticiones las hace `background.js`).
- `autologin.js` — content script de `/login` (solo en la dirección configurada): entra con el token. Lo registra `background.js` (`contentScripts.register`) solo para el origen con permiso, igual que `youtube.js`; por eso el fondo es persistente.
- `popup.*`, `options.*`, `ui.css` — interfaz (variables por función: `--bg`, `--accent`, `--control`…).
- `themes.css`, `lib/themes.js` — temas, **generados** con `python -m scripts.themes` desde `core/themes.py` (las mismas
  paletas que el Panel); `theme-init.js` aplica el elegido antes de pintar.
- `icons.svg` — iconos Lucide; se regenera con `python -m scripts.build_extension --solo-iconos`.

API del Panel que usa: `GET /api/ext/status`, `GET/POST /api/items` (desde la 2.2; las anteriores usan `POST /api/inbox`, que sigue aceptándose), `PATCH /api/items/{id}`,
`POST /api/capture` (prefijos y eventos, con `dry_run` para la vista previa), `GET /api/calendar/agenda`,
`PATCH /api/calendar/events/{id}`, `POST /api/routines/{id}/check`, `POST /api/resources`, `GET /api/resources/categories`, `GET /api/ext/categoria` (2.10),
`POST /api/ext/sesion` (2.9: el token por una cookie de sesión; solo vale el token de la extensión, no el del escritorio).
`GET /healthz` (público; 2.11: reconocer el Panel al detectar) y `POST /api/red/latido` (2.11).
Todo con el mismo token (`Authorization: Bearer`). Tests: `tests/e2e/test_extension.py` (popup, opciones y fondo contra el
servidor de pruebas, con la API `browser.*` simulada).
