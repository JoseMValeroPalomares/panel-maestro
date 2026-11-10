# CLAUDE.md · Comidas (`comidas/`)

Se carga al trabajar en esta carpeta; las reglas generales y la sección «Ojo» están en el `CLAUDE.md` de la raíz.

Scripts (desde la raíz del proyecto):

```bash
python comidas/bulk_edit_meals.py                    # ediciones masivas (cp comidas/data/comidas.db{,.bak} antes; tiene dry_run)
python comidas/list_comidas_db.py                    # vuelca la BD a comidas/data/export/*.csv
python comidas/seed_data.py                          # siembra ingredientes/comidas nuevos
```

- **Comidas**: franjas en la tabla `franjas` (`_sync_franjas()` refresca las constantes del generador; `dias` = en qué días se usa cada una, `franja_en_dia`), papel de cada plato (`rol`), plato doble, plantillas, favoritos y registro corporal en `comidas/planner.py` (router incluido al final de `comidas/main.py`).
- **Comidas (`comidas/`)**: BD propia `comidas/data/comidas.db`, esquema y migraciones ligeras en `comidas/database.py:init_db` (aditivas: nunca borran; si `ingredients` no tiene `nombre`, se renombra a `ingredients_legacy_*`). La lógica del generador/planificador (constantes de franjas, grupos de alimentos, límites semanales, escalado de raciones) está en `comidas/main.py` (Python puro, sin numpy/scipy). Cada celda de `weekly_plan` puede llevar su propio `gramos_racion`; si es NULL se usa la ración estándar del catálogo.
