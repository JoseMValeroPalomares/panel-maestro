/* ==========================================================================
   plantillas-catalogo.js — plantillas de tablero de serie (P-4), window.PlantillasCatalogo
   Solo datos: cada una es una lista de formas [tipo, x, y, ancho, alto, texto, color, {extra}] y de enlaces
   [desde, hasta, etiqueta]. Todas sobre una rejilla de 20 px: columnas de 240 de ancho con 20 de hueco, cajas de 60
   de alto y contenedores con sitio para escribir. Las dibuja board.js (tpl) y las pinta en miniatura plantillas.js.
   ========================================================================== */
(function () {
  'use strict';
  const C = { azul: '#89b4fa', verde: '#a6e3a1', rojo: '#f38ba8', amarillo: '#f9e2af', melocoton: '#fab387', malva: '#cba6f7',
    turquesa: '#94e2d5', cielo: '#89dceb', gris: '#7f849c', lavanda: '#b4befe' };
  const T = (text, x, y, w = 600, size = 24) => ['text', x, y, w, 44, text, null, { fontSize: size }];
  const DIAS = ['Lunes', 'Martes', 'Miércoles', 'Jueves', 'Viernes'];

  const tablero = [
    {
      key: 'semana-examenes', name: 'Semana de exámenes', tags: 'universidad estudio calendario',
      desc: 'Cada día en su columna con el examen y el repaso del siguiente; abajo, lo pendiente y las dudas.',
      nodes: [
        T('Semana de exámenes', 0, 0),
        ...DIAS.map((d, i) => ['container', i * 260, 60, 240, 380, d, i % 2 ? C.azul : C.rojo]),
        ...DIAS.map((d, i) => ['rect', i * 260 + 20, 120, 200, 60, i % 2 ? 'Repaso · asignatura' : 'Examen · 10:00', i % 2 ? C.azul : C.rojo]),
        ...DIAS.map((d, i) => ['rect', i * 260 + 20, 200, 200, 60, i < 4 ? `Repasar lo de ${DIAS[i + 1].toLowerCase()}` : 'Descansar', i < 4 ? C.lavanda : C.verde]),
        ['sticky', 0, 480, 360, 180, 'Pendiente de repasar', C.amarillo],
        ['sticky', 400, 480, 360, 180, 'Dudas para el profesor', C.melocoton],
        ['sticky', 800, 480, 480, 180, 'Material: apuntes, exámenes de otros años, calculadora…', C.verde],
      ],
      links: [],
    },
    {
      key: 'practica', name: 'Práctica de asignatura', tags: 'universidad entrega flujo',
      desc: 'Del enunciado a la entrega en seis pasos, con la rúbrica y las dudas a la vista.',
      nodes: [
        T('Práctica · asignatura', 0, 0),
        ['ellipse', 0, 80, 180, 80, 'Enunciado', C.malva],
        ['rect', 220, 90, 200, 60, 'Entender lo que piden', C.azul],
        ['rect', 460, 90, 200, 60, 'Diseño / esquema', C.azul],
        ['rect', 700, 90, 200, 60, 'Hacerla', C.azul],
        ['rect', 940, 90, 200, 60, 'Probar y revisar', C.azul],
        ['ellipse', 1180, 80, 180, 80, 'Entregar', C.verde],
        ['container', 0, 220, 640, 240, 'Rúbrica · lo que puntúa', C.amarillo],
        ['container', 680, 220, 680, 240, 'Dudas y decisiones', C.melocoton],
      ],
      links: [[1, 2], [2, 3], [3, 4], [4, 5], [5, 6]],
    },
    {
      key: 'proyecto-versiones', name: 'Proyecto con versiones', tags: 'proyecto versiones hoja de ruta',
      desc: 'Lo mínimo, las mejoras y lo que hace falta para publicar, cada versión en su columna.',
      nodes: [
        T('Proyecto · nombre', 0, 0),
        ['ellipse', 0, 160, 160, 80, 'Idea', C.malva],
        ['container', 200, 60, 280, 360, 'v0.1 · lo mínimo', C.azul],
        ['rect', 220, 120, 240, 60, 'Lo imprescindible', C.azul],
        ['rect', 220, 200, 240, 60, 'Probarlo de verdad', C.azul],
        ['container', 520, 60, 280, 360, 'v0.2 · mejoras', C.malva],
        ['rect', 540, 120, 240, 60, 'Lo que más se echa en falta', C.malva],
        ['rect', 540, 200, 240, 60, 'Arreglos', C.malva],
        ['container', 840, 60, 280, 360, 'v1.0 · publicar', C.verde],
        ['rect', 860, 120, 240, 60, 'Documentación', C.verde],
        ['rect', 860, 200, 240, 60, 'Publicar y avisar', C.verde],
        ['sticky', 1160, 60, 240, 200, 'Fuera de alcance (por ahora)', C.amarillo],
      ],
      links: [[1, 2], [2, 5], [5, 8]],
    },
    {
      key: 'estudio-tema', name: 'Estudio de un tema', tags: 'universidad estudio mapa',
      desc: 'El tema en el centro y alrededor conceptos, definiciones, ejemplos y dudas; un resumen al final.',
      nodes: [
        ['ellipse', 400, 200, 240, 100, 'Tema', C.malva],
        ['rect', 0, 40, 280, 120, 'Conceptos clave', C.azul],
        ['rect', 760, 40, 280, 120, 'Definiciones y fórmulas', C.turquesa],
        ['rect', 0, 340, 280, 120, 'Ejemplos resueltos', C.verde],
        ['rect', 760, 340, 280, 120, 'Dudas', C.melocoton],
        ['sticky', 340, 400, 360, 160, 'Resumen en cinco líneas', C.amarillo],
      ],
      links: [[0, 1], [0, 2], [0, 3], [0, 4]],
    },
    {
      key: 'plan-entrega', name: 'Plan de entrega', tags: 'entrega fechas plan',
      desc: 'Hacia atrás desde la fecha límite: borrador, revisión y entrega, y la lista final.',
      nodes: [
        T('Entrega · fecha límite', 0, 0),
        ['rect', 0, 80, 220, 60, 'Hoy · leer el enunciado', C.azul],
        ['rect', 260, 80, 220, 60, '−7 días · borrador', C.malva],
        ['rect', 520, 80, 220, 60, '−3 días · revisión', C.amarillo],
        ['rect', 780, 80, 220, 60, '−1 día · formato', C.melocoton],
        ['ellipse', 1040, 70, 200, 80, 'Entregar', C.verde],
        ['container', 0, 200, 480, 260, 'Lista final', C.verde],
        ['text', 20, 250, 440, 180, '☐ Nombre y portada\n☐ Formato pedido\n☐ Referencias\n☐ Archivo correcto\n☐ Copia guardada', null, { fontSize: 16 }],
        ['sticky', 520, 200, 360, 260, 'Riesgos y plan B', C.rojo],
      ],
      links: [[1, 2], [2, 3], [3, 4], [4, 5]],
    },
    {
      key: 'lluvia-ideas', name: 'Lluvia de ideas', tags: 'ideas creatividad',
      desc: 'La pregunta arriba, ocho notas para soltar ideas sin filtro y una columna para las mejores.',
      nodes: [
        ['diamond', 300, 0, 320, 120, '¿Pregunta?', C.malva],
        ...[0, 1, 2, 3].map((i) => ['sticky', i * 220, 160, 200, 160, '', [C.amarillo, C.melocoton, C.verde, C.cielo][i]]),
        ...[0, 1, 2, 3].map((i) => ['sticky', i * 220, 340, 200, 160, '', [C.cielo, C.verde, C.amarillo, C.melocoton][i]]),
        ['container', 900, 160, 280, 340, 'Las mejores', C.verde],
      ],
      links: [],
    },
    {
      key: 'pros-contras', name: 'Pros y contras', tags: 'decidir decisión',
      desc: 'Dos columnas con tres razones cada una y la decisión debajo.',
      nodes: [
        ['container', 0, 0, 300, 300, 'Pros', C.verde],
        ['rect', 20, 60, 260, 60, '+', C.verde], ['rect', 20, 140, 260, 60, '+', C.verde], ['rect', 20, 220, 260, 60, '+', C.verde],
        ['container', 340, 0, 300, 300, 'Contras', C.rojo],
        ['rect', 360, 60, 260, 60, '−', C.rojo], ['rect', 360, 140, 260, 60, '−', C.rojo], ['rect', 360, 220, 260, 60, '−', C.rojo],
        ['diamond', 200, 340, 240, 120, 'Decisión', C.malva],
      ],
      links: [],
    },
    {
      key: 'matriz', name: 'Matriz urgente / importante', tags: 'prioridad eisenhower decidir',
      desc: 'Cuatro cajas para repartir las tareas: hazlo ya, planifícalo, delégalo o descártalo.',
      nodes: [
        T('Urgente', 220, 0, 200, 18), T('No urgente', 540, 0, 200, 18),
        ['container', 160, 40, 300, 240, 'Hazlo ya', C.rojo], ['container', 480, 40, 300, 240, 'Planifícalo', C.azul],
        ['container', 160, 300, 300, 240, 'Delégalo', C.amarillo], ['container', 480, 300, 300, 240, 'Descártalo', C.gris],
        T('Importante', 0, 140, 140, 16), T('No importante', 0, 400, 140, 16),
      ],
      links: [],
    },
    {
      key: 'kanban', name: 'Kanban', tags: 'columnas tablero tareas',
      desc: 'Por hacer, haciendo, bloqueado y hecho; arrastra tus tareas del Inbox a cada columna.',
      nodes: [
        ['container', 0, 0, 260, 440, 'Por hacer', C.azul], ['rect', 20, 60, 220, 60, 'Tarea', C.azul], ['rect', 20, 140, 220, 60, 'Tarea', C.azul],
        ['container', 280, 0, 260, 440, 'Haciendo', C.amarillo], ['container', 560, 0, 260, 440, 'Bloqueado', C.rojo],
        ['container', 840, 0, 260, 440, 'Hecho', C.verde],
      ],
      links: [],
    },
    // Las de antes, con su sitio en el catálogo
    {
      key: 'tarea-pasos', name: 'Tarea con pasos', tags: 'pasos flujo', desc: 'Un objetivo arriba y tres pasos enlazados.',
      nodes: [['rect', 0, 0, 240, 60, 'Objetivo', C.turquesa], ['rect', 0, 100, 240, 60, 'Paso 1'], ['rect', 0, 180, 240, 60, 'Paso 2'], ['rect', 0, 260, 240, 60, 'Paso 3']],
      links: [[0, 1], [1, 2], [2, 3]],
    },
    {
      key: 'decision', name: 'Decisión', tags: 'decidir rombo', desc: 'Una pregunta y sus dos salidas.',
      nodes: [['diamond', 120, 0, 200, 120, '¿Decisión?', C.malva], ['rect', 0, 180, 180, 60, 'Sí', C.verde], ['rect', 260, 180, 180, 60, 'No', C.rojo]],
      links: [[0, 1, 'Sí'], [0, 2, 'No']], route: 'orthogonal',
    },
    {
      key: 'flujo', name: 'Diagrama de flujo', tags: 'flujo proceso', desc: 'Inicio, proceso, condición y fin.',
      nodes: [['ellipse', 40, 0, 160, 80, 'Inicio', C.verde], ['box', 30, 120, 180, 60, 'Proceso'], ['diamond', 30, 220, 180, 120, '¿Condición?', C.amarillo], ['ellipse', 40, 380, 160, 80, 'Fin', C.rojo]],
      links: [[0, 1], [1, 2], [2, 3, 'Sí']], route: 'orthogonal',
    },
    { key: 'nota', name: 'Nota adhesiva', tags: 'nota', desc: 'Una nota en blanco.', nodes: [['sticky', 0, 0, 180, 160, '', C.amarillo]], links: [] },
    {
      key: 'rutina-pasos', name: 'Rutina por pasos', tags: 'rutina pasos', desc: 'Un flujo con la hora de empezar y la duración de cada paso.',
      nodes: [['ellipse', 20, 0, 200, 60, 'Empieza · 07:30', C.malva], ['rect', 0, 100, 240, 60, 'Paso 1 · 10 min'], ['rect', 0, 180, 240, 60, 'Paso 2 · 15 min'],
        ['rect', 0, 260, 240, 60, 'Paso 3 · 5 min'], ['ellipse', 20, 360, 200, 60, 'Hecha', C.verde]],
      links: [[0, 1], [1, 2], [2, 3], [3, 4]],
    },
    {
      key: 'dia-rutinas', name: 'Día por rutinas', tags: 'rutina día mañana tarde noche', desc: 'El día en mañana, tarde y noche con sus bloques.',
      nodes: [['container', 0, 0, 240, 300, 'Mañana', C.amarillo], ['rect', 20, 60, 200, 60, '07:30 · Despertar'], ['rect', 20, 140, 200, 60, '08:00 · Desayuno'],
        ['container', 260, 0, 240, 300, 'Tarde', C.melocoton], ['rect', 280, 60, 200, 60, '17:00 · Estudio'], ['rect', 280, 140, 200, 60, '19:00 · Gimnasio'],
        ['container', 520, 0, 240, 300, 'Noche', C.malva], ['rect', 540, 60, 200, 60, '21:00 · Cena'], ['rect', 540, 140, 200, 60, '23:00 · Leer']],
      links: [],
    },
  ];

  window.PlantillasCatalogo = { tablero, COLORS: C };
})();
