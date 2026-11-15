# CLAUDE.md · Comidas (`comidas/`)

Se carga al trabajar en esta carpeta; las reglas generales y la sección «Ojo» están en el `CLAUDE.md` de la raíz.

Scripts (desde la raíz del proyecto):

```bash
python -m scripts.comidas.bulk_edit_meals            # ediciones masivas (dry_run; al escribir copia antes la BD a backups/scripts-comidas/)
python -m scripts.comidas.list_comidas_db            # vuelca la BD a comidas/data/export/*.csv (solo lectura)
python -m scripts.comidas.seed_data                  # siembra ingredientes/comidas nuevos (también seed_cenas; idempotentes, con copia previa)
```

- **Comidas**: franjas en la tabla `franjas` (`_sync_franjas()` refresca las constantes del generador; `dias` = en qué días se usa cada una, `franja_en_dia`), papel de cada plato (`rol`), plato doble, plantillas, favoritos y registro corporal en `comidas/planner.py`.
- **Comidas (`comidas/`)**: BD propia `comidas/data/comidas.db`, esquema y migraciones ligeras en `comidas/database.py:init_db` (aditivas: nunca borran; si `ingredients` no tiene `nombre`, se renombra a `ingredients_legacy_*`). La lógica del generador (grupos de alimentos, límites semanales, escalado de raciones, puntuación) está en `comidas/generador.py` (Python puro, sin numpy/scipy) y las franjas en `comidas/core.py`. Cada celda de `weekly_plan` puede llevar su propio `gramos_racion`; si es NULL se usa la ración estándar del catálogo.
- **Módulos** (A-1, como `app/main.py`): `main.py` solo crea la app, arranca e incluye los routers en este orden, que es el de emparejado: `ingredientes.py`, `platos.py` (fotos en caché local), `compra.py`, `plan.py` (celdas, plan completo `_plan_state`, generar/regenerar y sugerencias), `perfil.py`, la página `/`, `bulk.py` y `planner.py`; el `StaticFiles` en `/` va el último. `core.py` (modelos, `DIAS_SEMANA`, franjas con `_sync_franjas`, `_recipe_index`, ingredientes de una receta, `_slot_id`) y `generador.py` (catálogo, estado de la semana, `_score_candidate`, `generar_semana`, `regenerar_celda`) no tienen rutas. Nada importa de `comidas.main`: solo reexporta unos nombres antiguos (`_ORIGEN`), y asignarlos ahí (monkeypatch en tests) los cambia en su módulo real. Las constantes de franjas (`SLOT_WEIGHTS_BASE`, `FRANJA_ORDEN`, `CATALOGO_DE`…) se cambian en el sitio: impórtalas, no las reasignes. Ruta nueva: en su router, respetando el orden; si cambia el OpenAPI a propósito, que sea lo único que cambie.
