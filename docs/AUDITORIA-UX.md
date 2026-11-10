# Auditoría UX — Fase 1

Fecha: 2026-11-09 · Base: commit `9a09298` · Sin cambios de código.

## Método

- Las 19 pantallas recorridas a **1280×800** y **375×812** en una copia del panel (puerto 8811, datos copiados, sin
  puentes ni programador). Tema Mocha y comprobación en Claro.
- Medido en cada pantalla: errores de consola, desbordamiento horizontal, controles sin nombre accesible, objetivos
  táctiles por debajo de 44 px, texto por debajo de 12 px, encabezados `h1`, orden de tabulación.
- Lectura del código de estados de carga, vacío y error (`hoy.js`, `item-list.js`, `cerebro.js`, `economia.js`…).
- Capturas «antes» en `docs/capturas/ux-antes/` (ignorado por git: muestran datos personales).

## Lo que ya está bien (no tocar)

- **0 errores de consola y 0 desbordamientos horizontales** en las 38 combinaciones pantalla × ancho.
- Todos los botones de solo icono tienen `aria-label`; un solo `h1` por pantalla; enlace «Saltar al contenido»;
  foco visible de 2 px en `accent`; `prefers-reduced-motion` respetado; contraste AA comprobado por `test_tema.py`
  en los 9 temas.
- Una sola familia de iconos (Lucide), un sistema de diseño con tokens y un único modal. Los temas claro y oscuro se
  ven cuidados.
- Captura con prefijos, paleta Ctrl+K, atajos G + letra y ayuda con `?`: la base de la productividad ya existe.

---

## Problemas encontrados

Impacto: **A** alto (frena el uso diario o confunde), **M** medio, **B** bajo.
Esfuerzo: **S** pequeño (horas, CSS/JS local), **M** medio (un componente o varias pantallas), **L** grande (requiere
decidir cómo se reorganiza algo).

### 1. Navegación

| ID | Problema | Dónde | Imp. | Esf. |
|---|---|---|---|---|
| N-1 | **Funciones duplicadas entre secciones**: Inbox y Tareas muestran la misma lista con los mismos filtros; hay tres búsquedas distintas (Buscar, la de Notas y la paleta); el repaso vive en Repaso, en el modal de Flashcards de Notas y en la tarjeta de Hoy; Gestión duplica el «Gestor de notas» (modal en Notas). No se sabe cuál es «el sitio» de cada cosa. | Global | A | L |
| N-2 | **En móvil, el Inbox abre en el tablero** (lienzo con herramientas de dibujo) y la lista queda detrás de «Lista». En el móvil lo habitual es revisar y marcar. | Inbox | A | S |
| N-3 | **Barra inferior móvil**: Hoy, Inbox, Notas, Comidas. Calendario y Tareas, de uso diario, están en «Más» (dos toques y desplazarse por una lista de 18). | Móvil | A | S |
| N-4 | **Barra lateral larga**: 18 destinos + 3 en el pie. A 800 px de alto, el grupo Sistema y el pie (Capturar, Conexiones, **Ajustes**) quedan bajo el pliegue: para cambiar el tema o cerrar sesión hay que desplazar el menú. | Escritorio | M | M |
| N-5 | **La insignia del Inbox suma todo lo pendiente** (16: tareas del Inbox, casillas de las notas e ideas), no lo que falta por procesar en el Inbox, y va en rojo (color de error). Una cifra que nunca baja deja de informar y genera presión. | Shell | M | S |
| N-6 | En Hoy el botón se llama «Ctrl K» (el atajo, no la acción) y en móvil se queda en un ⌘ sin significado táctil. | Hoy | B | S |

### 2. Jerarquía visual

| ID | Problema | Dónde | Imp. | Esf. |
|---|---|---|---|---|
| J-1 | **Azulejos de color repetidos**: Calendario = Grafo (azul), Hoy = Baúl (ocre), Revisión = Rendimiento = Tareas (verde azulado), Papelera = Copias, Repaso = Estudio (morado). La firma visual pierde su función: orientarse por color. | Shell | M | S |
| J-2 | **Filtros apilados**: en Tareas, el estado está en la cabecera y el tipo, la categoría, la búsqueda y «Seleccionar» en el cuerpo, bajo la captura. En el Inbox hay tres filas de controles segmentados (Lista/7 días/Plantilla, Pendientes/Hechas, Todo/Tareas/Ideas/Rutinas). En móvil, la primera tarea aparece a ~400 px. | Tareas, Inbox | A | M |
| J-3 | **Tarjeta de tarea con demasiadas señales del mismo peso**: fecha, prioridad con fondo de color y bandera, categoría con icono de etiqueta, enlace a la nota, «hace 5 días», botón ⊕. Casi todas son «prioridad media» en naranja: el color ya no distingue. | Lista de ítems | A | M |
| J-4 | **Título repetido** en las notas cuyo cuerpo empieza con `# Título`: en lectura aparece dos veces (tres en móvil: cabecera, título y H1). | Notas | M | S |
| J-5 | **Rendimiento**: nombres técnicos sin explicación («Balance metabólico», «Calidad de codificación», «Eficiencia de rotación») y la insignia «Sin datos» **se monta sobre el título** «Sueño y termorregulación» a 1280 px (error de maquetación). | Rendimiento | M | S |
| J-6 | **Comidas, semana vacía** = 35 celdas idénticas con «+ Añadir»; el botón «Generar semana» no destaca como primer paso. | Comidas | M | S |
| J-7 | **Agenda del calendario inundada** por los 12 bloques de la rutina diaria: el evento real del día queda entre ellos. El interruptor «Rutinas» existe, pero el valor por defecto es mostrarlas. | Calendario | M | S |
| J-8 | Economía: «Gasto de los últimos 6 meses» sin datos muestra solo los nombres de los meses, sin mensaje. | Economía | B | S |
| J-9 | Hoy: las seis tarjetas ocupan lo mismo vacías que llenas; un día tranquilo es una rejilla de «no hay nada». | Hoy | M | M |

### 3. Número de clics y flujos

| ID | Problema | Dónde | Imp. | Esf. |
|---|---|---|---|---|
| C-1 | **El botón flotante (FAB) tapa contenido** en escritorio y móvil: el ⊕ de la última tarjeta visible, los «…» de Rutinas, la celda del domingo en Comidas y los eventos en Calendario. En escritorio además está duplicado (formulario de captura + «Capturar» en la barra + FAB). | Hoy, Tareas, Calendario, Rutinas, Comidas, Economía, Baúl | A | S |
| C-2 | **Barra de formato del editor cortada** a 1280 px con la barra lateral abierta: 25 botones, los últimos (simulación, flashcard, dividir, marcas) quedan fuera y no se ve que se pueda desplazar. | Notas | M | M |
| C-3 | En móvil, la **portada de Notas no se carga** (`renderNotesHome` sale si el ancho es < 768 px): solo «Elige una nota», sin recientes ni pendientes. | Notas (móvil) | M | S |
| C-4 | **Acciones de solo icono sin texto en táctil**: el ⊕ de cada tarjeta («Añadir un paso», solo con `title`), los 4 iconos de cada franja en Comidas móvil (copiar, plantilla, añadir, ocultar). En táctil no hay *hover*. | Lista, Comidas | M | S |
| C-5 | Acciones repetidas en Notas: «Repasar» (cabecera) y «Una al azar» (portada) hacen lo mismo; «Nueva nota» aparece dos veces en la misma vista. | Notas | B | S |

### 4. Consistencia

| ID | Problema | Dónde | Imp. | Esf. |
|---|---|---|---|---|
| K-1 | **El mismo icono con dos significados**: ★ es «Para más tarde» en el Baúl y «Favorito» en Comidas. `calendar-days` (Repaso) es casi igual a `calendar` (Calendario). `history` es a la vez Revisión y «Seguir escribiendo». | Baúl, Comidas, navegación | M | S |
| K-2 | **La acción principal cambia de sitio**: en Economía, Rutinas y Baúl va en la cabecera; en Tareas y Hoy es un formulario en el cuerpo; en Baúl, además, hay FAB. | Global | M | M |
| K-3 | **Nombres que no coinciden**: menú «Copias» frente al título «Copias de seguridad»; «Revisión» frente a «Revisión semanal»; «Inbox» es el único término en inglés; «Gestión» no dice qué gestiona. | Navegación | B | S |
| K-4 | Glifos de texto como icono (`✓` en menús de estado y prioridad, `★` en Comidas) y letras «R» y «E» en la barra del editor. | Notas, lista, Comidas | B | S |

### 5. Estados vacío, carga y error

| ID | Problema | Dónde | Imp. | Esf. |
|---|---|---|---|---|
| E-1 | **Error de carga desigual y sin «Reintentar»**: Hoy solo avisa en la tarjeta Agenda y el resto queda vacío; la portada de Notas, si falla, enseña el mensaje de bienvenida como si no hubiera notas; la lista dice «recarga». Ninguna ofrece un botón para reintentar. | Hoy, Notas, Tareas | M | S |
| E-2 | **Estados vacíos correctos pero planos**: el mismo icono en círculo para «aún no hay nada», «todo hecho» y «no se pudo cargar»; no distinguen entre éxito, vacío y error. Sin ilustraciones. | Global (~50 usos) | M | M |

### 6. Accesibilidad

| ID | Problema | Dónde | Imp. | Esf. |
|---|---|---|---|---|
| A-1 | **Objetivos táctiles por debajo del principio del proyecto (44 px)**: en móvil, los chips y controles segmentados miden 28–30 px de alto y los botones de icono 30–36 px (Hoy 18 controles, Comidas 41, Calendario 98). Se cumple WCAG 2.2 AA (≥ 24 px), no el estándar propio. | Móvil | M | M |
| A-2 | **Texto por debajo de 12 px**: etiquetas de la barra inferior (11 px), horas y fechas de la rejilla del calendario (31–37 elementos) y el mapa de Repaso. | Móvil, Calendario, Repaso | M | S |
| A-3 | **El grafo no tiene alternativa accesible**: el lienzo de vis-network es enfocable sin nombre ni lista equivalente para lector de pantalla o teclado. | Grafo | M | M |
| A-4 | El título y el cuerpo del editor de notas quitan el contorno de foco (`outline: none`); con teclado solo se ve el cursor. | Notas | B | S |
| A-5 | Hacen falta 22 tabulaciones para cruzar el menú lateral (mitigado por «Saltar al contenido»). | Shell | B | — |

### 7. Responsive

| ID | Problema | Dónde | Imp. | Esf. |
|---|---|---|---|---|
| R-1 | El FAB no reserva espacio al final de la página: el último elemento queda debajo (ver C-1). | Móvil | A | S |
| R-2 | Inbox móvil empieza en el tablero (ver N-2); en Tareas, los filtros ocupan media pantalla (ver J-2). | Móvil | A | M |
| R-3 | La categoría con chips del Baúl y las pestañas de estado de Notas se cortan sin indicar que se desplazan. | Baúl, Notas | B | S |

### 8. Iconografía y recursos gráficos

| ID | Problema | Dónde | Imp. | Esf. |
|---|---|---|---|---|
| I-1 | Metáforas cruzadas (K-1): ★ = más tarde, `eye-off` = «no usar este día», `circle-plus` = «añadir paso» (parece «añadir tarea»). | Varios | M | S |
| I-2 | **Iconos de sección poco distintivos** en un vistazo: Repaso/Calendario (dos calendarios), Revisión (un reloj de historial), Gestión (una tabla genérica). | Navegación | M | S |
| I-3 | **Icono de la app** = el `brain` de Lucide sobre un cuadrado morado: genérico, sin versión monocroma ni variante clara/oscura; el favicon es el mismo PNG en todos los temas. La extensión tiene su propia copia. | PWA, favicon, extensión | M | S |
| I-4 | Estados vacíos, de carga y de error sin ilustración propia (ver E-2). | Global | B | M |
| I-5 | Glifos y letras como icono (K-4). | Notas, Comidas | B | S |

---

## Priorización

Orden propuesto (impacto alto y esfuerzo bajo primero). «Grupo» indica con qué se resolvería junto.

| # | ID | Qué | Imp. | Esf. | Grupo |
|---|---|---|---|---|---|
| 1 | C-1 / R-1 | FAB que no tape contenido (y fuera en escritorio, donde ya hay captura) | A | S | Shell |
| 2 | N-2 | Inbox móvil abre en la lista | A | S | Inbox |
| 3 | N-3 | Barra inferior móvil con Calendario y Tareas (elegible) | A | S | Shell |
| 4 | J-5 | Rendimiento: arreglar el solape de la insignia y explicar los nombres | M | S | Rendimiento |
| 5 | J-1 / I-2 | Un color y un icono distinto por sección | M | S | Iconos |
| 6 | K-1 / I-1 / K-4 / I-5 | Un significado por icono (★, ✓, R/E, ⊕) | M | S | Iconos |
| 7 | J-4 | No repetir el título de la nota en lectura | M | S | Notas |
| 8 | C-3 | Portada de Notas también en móvil | M | S | Notas |
| 9 | E-1 | Errores de carga uniformes con «Reintentar» | M | S | Estados |
| 10 | C-4 | Texto visible en acciones táctiles de solo icono | M | S | Lista, Comidas |
| 11 | J-7 | Agenda: rutinas plegadas en una línea por defecto | M | S | Calendario |
| 12 | J-6 / J-8 | Vacíos de Comidas y Economía que digan qué hacer | M | S | Estados |
| 13 | N-5 | Insignia del Inbox: solo lo sin procesar y sin rojo | M | S | Shell |
| 14 | A-2 | Nada de texto por debajo de 12 px | M | S | Sistema de diseño |
| 15 | J-2 / R-2 | Una sola barra de filtros (Tareas e Inbox), compacta en móvil | A | M | Lista |
| 16 | J-3 | Tarjeta de tarea con jerarquía: prioridad solo cuando importa | A | M | Lista |
| 17 | I-3 | Icono de la app propio con variantes | M | S | Iconos |
| 18 | A-1 | Objetivos de 44 px en móvil (chips, segmentados, iconos) | M | M | Sistema de diseño |
| 19 | C-2 | Barra del editor que se adapte (agrupar en un menú «Insertar») | M | M | Notas |
| 20 | N-4 | Barra lateral que quepa: Ajustes siempre visible | M | M | Shell |
| 21 | E-2 / I-4 | Estados vacío / éxito / error distintos con ilustraciones SVG | M | M | Estados |
| 22 | K-2 | Acción principal siempre en el mismo sitio | M | M | Global |
| 23 | J-9 | Hoy que se adapte al contenido (tarjetas vacías compactas) | M | M | Hoy |
| 24 | A-3 | Grafo: lista accesible equivalente | M | M | Grafo |
| 25 | N-1 | Un sitio claro para cada cosa (Inbox/Tareas, búsquedas, repaso, gestor) | A | L | Decisión de producto |
| 26 | C-5, K-3, N-6, A-4, R-3 | Detalles menores | B | S | Pulido |

N-1 es la de mayor impacto, pero exige decidir qué pantalla manda en cada caso. En la Fase 2 la planteo como
propuesta para que decidas tú, sin quitar ninguna función: lo duplicado pasaría a ser un acceso al sitio principal.
