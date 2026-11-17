# Contextos, Universidad y Proyectos

Todo sigue guardado **una sola vez**: los contextos, las asignaturas y los proyectos son etiquetas y contenedores
sobre las mismas tareas, eventos, esquemas, notas y recursos. Decisiones y riesgos: `AUDITORIA.md` (2026-11-11).

## Contextos

| Contexto | Para qué | Cómo se asigna |
|---|---|---|
| **Puntual** | Lo rápido del día a día (por defecto) | Lo que no dice otra cosa |
| **Universidad** | Clases, temas, entregas y exámenes | Con una asignatura (`@gabd`) o eligiéndolo |
| **Proyectos** | Construir cosas por versiones | Con un proyecto (`#panel-maestro`) o eligiéndolo |

El selector está arriba en Tareas, Inbox, Calendario y Hoy, y en la paleta (Ctrl+K → «Contexto: …»). Se guarda en el
servidor (preferencia `contexto`), así que la Waybar y la extensión ven el mismo. Lo nuevo que se crea desde una
lista filtrada va a ese contexto. La asignatura o el proyecto mandan sobre el contexto, y los pasos van con su tarea.
En una nota lo dice su frontmatter (`contexto:`, `asignatura: GABD`, `proyecto: panel-maestro`) y sus casillas lo heredan.

## Captura con menciones

```
t: práctica 4 @gabd viernes            → entrega de GABD el viernes
t: arreglar login #panel-maestro v0.3  → tarea del proyecto, versión v0.3
e: parcial 2 @ig 18/11 9:00            → examen de IG en el calendario
```
Una mención que no existe **no se crea**: se avisa (con la más parecida) y no se guarda nada. En rofi (Super+K),
`Alt+5` lista asignaturas y proyectos. Los alias de cada asignatura se editan en Universidad.

## Universidad

- **Portada** (`/universidad`): clases de hoy, próximas entregas y una tarjeta por asignatura (temas, prácticas,
  documentos, ejercicios, repasados y lo próximo). Clic en una = entrar (`?asignatura=`; Atrás vuelve). Pestañas de
  la portada: Asignaturas, Entregas y exámenes, Horario y Tareas (de todas).
- **Dentro de una asignatura**: cabecera (profesor, aula, media, carpeta, «Organizar documentos», nota de clase, ⋯) y
  pestañas Temas, Prácticas, Ejercicios, Entregas, Horario y Tareas. En **Temas** y **Prácticas** cada tema es una
  sección plegable (se recuerda) con sus documentos como cuadrados (clic = lector o descarga; arrastrar a otro tema
  = moverlo solo en el panel; ⋯ = mover, devolver a su carpeta o **quitar del tema** con deshacer), un cuadrado
  «Añadir documentos» y sus ejercicios. Las secciones se ordenan arrastrando por el asa.
- **Repartir los documentos (automático)**: por el número del nombre o de su carpeta («Chuletario_Tema3»,
  «Relación 4», «tema3 - primera parte», «lesson3», «IGV_Practica2_pr2a», «Practica 3/…»). La propuesta de temas ya
  junta lo que tiene el mismo número; al sincronizar, un documento nuevo que cae en una carpeta sin número («Teoria»)
  o en ninguna va solo al tema que ya tiene su número (los temas nuevos no se crean solos). **Organizar documentos**
  enseña cada documento de la carpeta con su tema y las sugerencias ya puestas (creando «Tema N» / «Práctica N» si
  faltan, con el nombre que quieras): se guardan de golpe o se cambian una a una. Un documento de la Práctica 1
  guardado dentro de «Practica 5» no se mueve solo.
- **A mano**: «Añadir documentos» abre un explorador de la raíz (solo lectura) para marcar documentos sueltos o
  «toda esta carpeta», también de fuera de la carpeta de la asignatura; «Examinar…» elige la carpeta de una
  asignatura. Nada se mueve ni se copia en el disco. `CMakeLists.txt` no cuenta como documento.
- **Ajustes** (menú ⋯): carpeta raíz (en el equipo del servidor), raíz de proyectos y contexto de la Waybar.
- **Asignaturas desde las carpetas**: cada subcarpeta (hasta 2 niveles) es una candidata; pones sigla y nombre.
- **Carpeta de la asignatura**: relativa a la raíz, o la ruta completa si está dentro de ella (se guarda relativa).
  El diálogo la comprueba mientras escribes. Estado junto a la asignatura: vinculada, **no encontrada** (se movió o
  se renombró: «Volver a vincular» y los temas y archivos siguen ahí) o disco no disponible (raíz sin montar).
- **Temas**: subcarpeta = tema; PDF, docx, pptx, md… suelto = tema de un archivo; código, binarios, `build` y
  comprimidos no. **Sincronizar** no crea temas: marca lo que ya no está, pone al día los archivos y avisa de
  «N temas nuevos · Revisar y confirmar». En la propuesta cada uno trae título sugerido («T2 - Procesos» →
  «Tema 2 · Procesos», «P1» → «Práctica 1») y grupo (Teoría, Prácticas u Otros); se renombra, se ordena
  arrastrando, se **fusiona** con otro, se deja para luego o se **descarta** (no vuelve a proponerse; se recupera
  abajo en la misma propuesta). Tu orden, estado, nombre, grupo y apuntes se conservan. Nunca se borra ni se escribe
  nada en la carpeta; con el disco sin montar no se marca nada.
- **Documentos de un tema**: también los de subcarpetas (hasta 4 niveles), en tu orden (arrastrar), con la página por
  la que ibas. Lo que desaparece del disco queda en «No encontrados» sin perder la página y vuelve solo si reaparece.
  Fusionar: el tema fusionado deja de verse y sus archivos, ejercicios y tareas pasan al otro; «Separar» lo devuelve
  con sus archivos (los ejercicios y tareas se quedan donde están).
- **Lector de PDF**: dentro del panel (pdf.js, sin conexión a nada de fuera). Recuerda la última página; ← → página,
  + − zoom, 0 ajustar al ancho. Para buscar o copiar texto: «Abrir en una pestaña nueva» (abre en esa página).
- **Ejercicios**: de una asignatura y de uno o varios temas, con enunciado, dificultad (fácil, media, difícil),
  estado (pendiente / hecho), notas o solución y el PDF y la página donde están. Pestaña «Ejercicios» (en lista o
  por tema, filtros de tema, estado y dificultad; la búsqueda de arriba también) y debajo de cada tema.
  Borrar va a la papelera.
- **Entregas y exámenes**: las entregas son tareas (`Entrega`), los exámenes eventos del calendario; peso, nota y
  temas que entran; media ponderada de lo evaluado.
- **Horario**: cada clase es un evento que se repite hasta el fin del cuatrimestre (sale en Calendario, Hoy,
  Rutinas y Waybar; no se manda a iCloud ni al ESP32). «Convertir en clases» pasa la rutina de horario a evento.
- **Propuesta** (menú ⋯): tareas y eventos puntuales cuya categoría o sigla coincide con una asignatura, para
  confirmarlos en bloque (se puede deshacer).
- Anotaciones nuevas en las notas: `{{duda: …}}`, `{{examen: …}}`, `{{importante: …}}`, junto a las de siempre.

## Abrir carpetas

Los navegadores no abren `file://` desde una página http, y el servidor las abriría en su propia pantalla. Los
botones enlazan a `panelmaestro://abrir/<asignatura|tema|proyecto>/<id>`; en el equipo donde están las carpetas:

```bash
scripts/desktop/abrir/instalar.sh            # .desktop + xdg-mime (con copias *.bak-panel-<fecha>)
scripts/desktop/abrir/abrir.py --dry-run panelmaestro://abrir/asignatura/1   # qué abriría
scripts/desktop/abrir/instalar.sh --desinstalar
```

Seguridad: el abridor solo recibe un id. Pide al panel (con el token del escritorio) la ruta **relativa** y la
resuelve contra `~/.config/panel-maestro/abrir.conf` (600): sin rutas absolutas ni `..`, y con `realpath` dentro de
la raíz (un enlace simbólico que escape se rechaza). Cualquier otra cosa solo muestra un aviso. La primera vez,
Firefox pregunta con qué abrir el enlace: elige «Panel · abrir carpeta» y marca recordar.
Alternativa sin instalar nada: **Copiar ruta**, que funciona también por HTTP.

## Proyectos

**Lista** (`/proyectos`): tres vistas (`V` las alterna): tarjetas por estado (idea, en curso, pausado, terminado),
tablero por estado (arrastrar una tarjeta por su asa cambia su estado; con el teclado, Alt + flechas) y cronología
(del inicio al fin de cada proyecto; sin fechas, desde que se creó hasta su última versión con fecha). Búsqueda (`/`),
filtros por estado, prioridad y etiqueta, y orden manual, por nombre, progreso, fecha de fin, prioridad o recientes.
Búsqueda y filtros van en la URL. `N` crea un proyecto.

**Cada proyecto** tiene descripción en Markdown (se pliega si es larga), estado, prioridad, fechas de inicio y fin
(con «quedan N días» o «vencido»), etiquetas y progreso (tareas hechas / tareas). Pestañas (`1`–`7`):

- **Tareas**: **por versión** (la de por defecto): una sección por versión con hueco entre ellas (abiertas, «Sin
  versión» y las cerradas plegadas; plegar se recuerda); arrastrar una tarea a otra versión la cambia. Las
  **subtareas se ven debajo de cada tarea** (plegar por tarea, se recuerda; las hechas empiezan plegadas): se marcan,
  se añaden (icono «+» de la tarea; Enter añade y deja seguir escribiendo, Esc cierra) y se cambian (clic en el texto)
  sin abrir nada. También tablero agrupado por estado, versión o prioridad (dentro de cada columna, separadas por
  versión y con sus subtareas) (arrastrar entre columnas cambia ese dato), lista en
  tabla ordenable por columnas (tarea, estado, prioridad, fecha, versión, avance) o cronología (cada tarea desde que se
  creó hasta su fecha; las versiones con fecha objetivo como hitos). Búsqueda (también en descripciones y subtareas) y
  filtros por prioridad y versión, en la URL. `N` lleva a la captura.
- **Detalles de una tarea** (clic en su título; ventana centrada): título, estado, prioridad, fecha y versión; descripción en Markdown cuyas
  casillas `- [ ]` son la **checklist** (se marcan con un clic, sin abrir el editor); **subtareas** (los pasos de
  siempre); **adjuntos** (arrastrar o elegir, 25 MB cada uno; imágenes y PDF se ven en el navegador, lo demás se
  descarga) y **comentarios** en Markdown (editar, borrar con deshacer). Cerrar la ficha guarda la descripción a medio
  editar y conserva el comentario sin enviar.
- **Versiones** (hitos): nombre (v0.1…), título, descripción y fecha objetivo; asignar tareas y cerrar → registro de
  cambios con lo hecho (editable; las abiertas pasan a otra versión).
- **Registro de cambios**: las versiones cerradas de la más nueva a la más vieja (y lo hecho de las abiertas como «Sin
  publicar»), con «Copiar como CHANGELOG.md».
- **Ideas**, **Esquemas** (tableros del Inbox de ese proyecto), **Bitácora** (una nota) y **Enlaces** con Git de solo
  lectura (último commit, rama y etiquetas de la carpeta del proyecto).

Comentarios y adjuntos van con su tarea: al borrarla se quedan aparte y vuelven si la restauras desde la papelera;
pasados 31 días sin ella, la purga diaria los quita. Los archivos viven en `data/adjuntos/` y entran en las copias.
