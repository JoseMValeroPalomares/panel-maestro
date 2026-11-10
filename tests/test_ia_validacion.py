"""Validador de las correcciones de IA (app/ia_validacion.py): casos buenos y cada tipo de rotura."""
import pytest

from app.ia_validacion import quitar_envoltorio, validar

ORIG = """# Ley de Ohm

La tension V = 12 V sobre una resistencia de 4 ohmios da $I = V/R$ = 3 A. Ver [[Corriente]] y [[tarea:7]].

$$P = V \\cdot I$$

| Magnitud | Unidad |
|---|---|
| V | voltio |

- [ ] Repasar ejercicios
- [x] Leer teoria

¿Que es la intensidad? >> Carga por segundo

```python
print(12)
```

{{resumir: todo depende de V}}
"""
TITULOS = {"Corriente", "Ohm"}


def bueno(**cambios):
    t = ORIG.replace("La tension", "La tensión").replace("teoria", "teoría")
    for a, b in cambios.items():
        t = t.replace(a, b)
    return t


def test_correccion_buena():
    assert validar(ORIG, bueno(), TITULOS) == []


@pytest.mark.parametrize("roto,frag", [
    (("$$P = V \\cdot I$$", "$$P = V \\cdot {I$$"), "Fórmula rota"),
    (("$I = V/R$", "I = V/R$"), "$"),
    (("|---|---|", "|---|"), "Tabla rota"),
    (("[[Corriente]]", "[[Inventada]]"), "no existe"),
    (("[[tarea:7]]", "[[tarea:8]]"), "tareas"),
    (("Repasar ejercicios", "Repasar ejercicios #fisica"), "etiquetas"),
    (("= 3 A", "= 4 A"), "números"),
    (("```python\nprint(12)\n```", "```python\nprint(12)"), "sin cerrar"),
    (("- [ ] Repasar", "- [x] Repasar"), "casillas"),
    (("¿Que es la intensidad? >> Carga por segundo", "La intensidad es carga por segundo"), "flashcards"),
    (("{{resumir: todo depende de V}}", "todo depende de V"), "anotaciones"),
])
def test_rechaza(roto, frag):
    t = bueno().replace(*roto)
    assert any(frag in p for p in validar(ORIG, t, TITULOS)), validar(ORIG, t, TITULOS)


def test_rechaza_etiquetas_frontmatter_y_recorte():
    assert any("metadatos" in p for p in validar(ORIG, "---\ntags: [a]\n---\n" + bueno(), TITULOS))
    assert any("Recorta" in p for p in validar(ORIG * 3, ORIG, TITULOS))
    assert validar(ORIG, "", TITULOS)


def test_comentario_revisar_permitido():
    assert validar(ORIG, bueno() + "\n<!-- REVISAR: ¿12 V o 120 V? -->\n", TITULOS) == []


def test_envoltorio():
    assert quitar_envoltorio("```markdown\n# Hola\n```") == "# Hola"
    assert quitar_envoltorio("```python\nx\n```") == "```python\nx\n```"
