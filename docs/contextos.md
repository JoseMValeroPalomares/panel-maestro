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

- **Ajustes** (menú ⋯): carpeta raíz (en el equipo del servidor), raíz de proyectos y contexto de la Waybar.
- **Asignaturas desde las carpetas**: cada subcarpeta (hasta 2 niveles) es una candidata; pones sigla y nombre.
- **Temas**: subcarpeta = tema; PDF, docx, pptx, md… suelto = tema de un archivo; código, binarios, `build` y
  comprimidos no. Grupos por nombre: Teoría, Prácticas u Otros. **Sincronizar** añade lo nuevo, marca lo que ya
  no está y nunca borra ni escribe en la carpeta; tu orden, estado, nombre, grupo y apuntes se conservan. Con el
  disco sin montar no se marca nada.
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

Tarjetas por estado (idea, en curso, pausado, terminado). Dentro: Tareas (lista o columnas por hacer / en curso /
hecho), Versiones (crear, asignar tareas, cerrar → registro de cambios con lo hecho, editable; las abiertas pasan a
otra versión), Ideas, Esquemas (tableros del Inbox de ese proyecto), Bitácora (una nota) y Enlaces con Git de solo
lectura (último commit, rama y etiquetas de la carpeta del proyecto).
