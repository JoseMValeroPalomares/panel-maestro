# Fase 4 — refactor y optimización

Fecha: 2026-11-09 · Rama `interfaz-fase3` · Referencia: `docs/INVENTARIO.md`.

**Resultado: no se ha perdido ninguna función.** Sin cambios de esquema de BD ni de formato de las notas.

## Qué cambia y por qué

| Área | Cambio | Por qué |
|---|---|---|
| Seguridad | CSP del panel con `script-src 'self'` (sin `'unsafe-inline'`). Los 78 `onclick` (72 en plantillas, 5 en HTML generado por JS y el de la página sin conexión) pasan a `data-call` + `data-args` en JSON, interpretados por un único despachador (`ui.js:runCall`). | Un script inyectado en la página ya no puede ejecutarse aunque alguien lograra colar HTML |
| Seguridad | Las simulaciones de las notas corren en `/sim` (`core/pwa.py`): documento propio con su CSP (`connect-src 'none'`, `sandbox allow-scripts`); el código llega por `postMessage`. | Necesitan JS en línea; así lo tienen solo ellas y aisladas (origen opaco, sin acceso a la API ni a las cookies) |
| Seguridad | El HTML saneado de notas y tareas no conserva atributos `data-*` (`ALLOW_DATA_ATTR: false`). | Con `data-call`, un botón escrito en una nota podría haber disparado acciones del panel |
| Rendimiento | KaTeX (≈ 280 KB) y highlight.js (≈ 120 KB) se piden la primera vez que una nota tiene fórmulas o código. | Abrir Notas ya no descarga ni interpreta ≈ 400 KB que la mayoría de notas no usa |
| Código muerto | Fuera `fabric.js` (312 KB en `static/vendor` y ≈ 1.700 líneas de dependencias en `package-lock.json`): no lo cargaba ninguna página; los tableros antiguos los convierte Python. Fuera `shadeColor` (Estudio), sin uso. | Menos peso y menos superficie que mantener |
| Duplicación | Un solo `categoryIndex`/`categoryColor` en `ui.js` para Notas, Grafo y Baúl. | El Baúl usaba otro hash: la misma categoría podía salir de otro color que en Notas. **Visible**: algunas categorías del Baúl cambian de color para coincidir con Notas y Grafo |
| Responsive | Calendario en móvil táctil: el título va en su línea; navegación, rutinas y horario debajo. | Antes el interruptor de rutinas caía solo en una fila (o el título quedaba en «L…») |

Revisado y sin cambios necesarios: secretos (solo en `.env`; en el código solo una IP de ejemplo en un texto de
ayuda de la extensión), importaciones Python sin uso (ninguna, análisis del AST), archivos JS/CSS sin referencias
(ninguno), funciones JS sin uso (solo la citada).

## Pruebas nuevas

- `tests/test_csp.py`: la CSP del panel no permite JS en línea; ningún manejador `on…=` ni `<script>` en línea en
  plantillas y JS; los `data-call` son nombres válidos con argumentos JSON; `/sim` es público, aislado y con su CSP.
- `tests/e2e/test_interfaz.py`: acciones `data-call` (incluida una con dos llamadas), librerías de Notas bajo demanda
  y título sin repetir, simulación ejecutándose en `/sim`, tooltip con el foco del teclado, error con «Reintentar»,
  pestañas del móvil que se eligen y se recuerdan, y una nota con un `data-call` escrito a mano que no hace nada.
- Ya existían (y siguen en verde) las de las funciones críticas del inventario: captura y prefijos, ítems y casillas
  de notas, calendario y rutinas, copias y restauración, papelera y deshacer, autenticación, SSRF, migraciones…

## Inventario

| IDs | Estado |
|---|---|
| S-01 – S-20 | Se conservan. S-07/S-13: los botones funcionan igual con `data-call`; S-20: login sin cambios |
| P-01 – P-21 | Se conservan. P-02: simulaciones, fórmulas y código igual (ahora bajo demanda); P-06: cabecera del calendario reordenada en móvil; P-10: colores de categoría alineados con Notas |
| K-01 – K-16 | Se conservan (los atajos no dependían de los `onclick`) |
| D-01 – D-05, F-01 – F-13 | Se conservan |
| E-01 – E-13 | Se conservan; E-08 (límites) refuerza: contenido saneado sin `data-*` |
| G-01 – G-05 | Se conservan |
