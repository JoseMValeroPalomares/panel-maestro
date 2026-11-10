# Guía de notas

<!--
  ESTE ARCHIVO ES TUYO. Lo he redactado a partir de la sintaxis real del editor (static/js/cerebro.js, app/notes_core.py)
  y del estilo de tus notas actuales (título «# …», secciones «## …» separadas por «---», negritas para conceptos,
  «## Ver también» con enlaces, flashcards «pregunta >> respuesta»). Edítalo cuanto quieras.

  · Todo lo que esté dentro de comentarios HTML como este NO se envía a la IA.
  · El resto SÍ se envía junto con cada nota, la lista de títulos existentes y las reglas fijas del sistema
    (no inventar datos, no etiquetas, conservar bloques…). Cuanto más corto y claro, mejor corrige y menos tokens gasta.
  · Si cambias un ejemplo, mantén el formato «✅ Bien» / «❌ Mal»: ayuda a los modelos pequeños.
  · Las etiquetas (tags) NO se usan en este sistema: no las añadas aquí como regla.
-->

Estas son las reglas de mis notas. Al corregir una nota aplica SOLO estas reglas de forma y estilo; nunca cambies el significado.

## 1. Estructura

- La nota empieza con un único título `# Título` (nivel 1), sin numerar.
- Después, un párrafo breve que define el concepto (1–3 frases).
- Las secciones usan `## Título` (nivel 2) y, si hace falta, `### Subsección` (nivel 3). No saltes de nivel (de `#` a `###`).
- Entre secciones principales se puede dejar una línea `---`.
- Si la nota enlaza con otras, termina con `## Ver también` y los enlaces separados por ` · `.

<!-- Extensión: mis notas son cortas y densas (200–600 palabras). La IA no debe alargar ni resumir. -->

## 2. Tono y redacción

- Español de España, directo, en presente, sin primera persona ni florituras.
- Frases cortas. Un párrafo = una idea.
- **Negrita** para el término clave la primera vez que aparece; *cursiva* solo para énfasis o términos extranjeros.
- Las listas se usan para enumerar partes o pasos, no para frases largas encadenadas.
- Corrige ortografía, tildes, puntuación y concordancia. No cambies términos técnicos ni unidades.

✅ Bien: `El **potencial de acción** es un cambio eléctrico rápido de la membrana.`
❌ Mal: `Pues básicamente el potencial de acción es como un cambio eléctrico que va rápido por la membrana, ¿vale?`

## 3. Fórmulas (LaTeX)

- En línea: `$I = V/R$`. En bloque, solo para ecuaciones importantes: `$$P = V \cdot I$$` (en su propio párrafo).
- Cierra siempre las llaves y los `$`. Usa `\cdot`, `\frac{a}{b}`, `\sqrt{x}`, `\Omega`, etc.
- El dinero o las unidades no llevan `$`: escribe `12 V`, `5 €`.
- Nunca cambies los valores ni las variables de una fórmula; solo arregla su sintaxis.

✅ Bien: `La potencia es $P = V \cdot I$.`
❌ Mal: `La potencia es $P = V * I` (falta el `$` de cierre) o `$$P = \frac{V}{R$$` (llave sin cerrar).

## 4. Tablas

- Tabla Markdown con fila de cabecera y separador, el mismo número de columnas en todas las filas.
- Úsalas para comparar cosas (≥ 2 columnas y ≥ 2 filas). Si es una lista simple, usa una lista.

```
| Magnitud | Unidad | Símbolo |
|---|---|---|
| Tensión | voltio | V |
| Intensidad | amperio | A |
```

❌ Mal: filas con menos columnas que la cabecera, o sin la línea `|---|---|`.

## 5. Bloques de código

- Con valla de tres comillas invertidas y lenguaje: ```` ```python ````. Siempre cerrada.
- No cambies el contenido del código; como mucho arregla una errata evidente.

## 6. Simulaciones interactivas

- Un bloque ```` ```sim ```` contiene una página HTML completa que se ejecuta en un recuadro aislado.
- **No lo reescribas**. Solo se permite arreglar una errata evidente o una etiqueta sin cerrar. Mantén el número de `<script>`.

## 7. Flashcards

- Una línea `Pregunta >> Respuesta` crea una tarjeta de repaso. Una por línea, sin saltos dentro.
- Conserva todas; solo corrige ortografía y redacción. No las conviertas en listas ni cambies el `>>`.

✅ Bien: `¿Qué es la hiperpolarización? >> Fase en la que el potencial baja por debajo del reposo.`

## 8. Anotaciones

- `{{resumir: …}}` (resumir esto), `{{entender: …}}` (lo que aún no entiendo), `{{mal: …}}` (creo que está mal).
- Son mis marcas personales: **no las borres, no las resuelvas y no cambies su tipo**. Solo ortografía.

## 9. Tareas

- Las casillas `- [ ]` / `- [x]` son tareas reales del panel. No las añadas, no las quites, no cambies su estado ni su orden.

## 10. Enlaces entre notas (en lugar de etiquetas)

- **No hay etiquetas**: no uses `#algo`, no escribas `tags:` ni «Etiquetas:». Las conexiones se hacen con enlaces.
- Enlaza con `[[Título exacto]]` solo notas de la lista de TÍTULOS EXISTENTES, con el título tal cual (mayúsculas y acentos incluidos).
- Enlaza la primera mención de un concepto que tenga nota propia, no todas las menciones.
- Si no existe la nota, **no inventes el enlace**: déjalo como texto normal.
- Los marcadores `[[tarea:12]]` son enlaces a tareas: déjalos exactamente igual.

✅ Bien: `Se explica en [[Potencial de acción]].` (existe en la lista)
❌ Mal: `Se explica en [[Potencial de acción en neuronas gigantes]].` (no existe) · `#neurociencia`

## 11. Datos y dudas

- No inventes datos, cifras, fechas ni nombres. No cambies números.
- Si un dato parece erróneo o dudoso, déjalo como está y añade debajo `<!-- REVISAR: motivo breve -->`.
- No añadas contenido nuevo (ejemplos, conclusiones, secciones) que no esté ya en la nota.
