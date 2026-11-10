# Auditoría de rendimiento

Página **Rendimiento** (menú «Vida») y tarjeta en **Hoy**. Funciona entera sin IA; la IA solo redacta la auditoría.

## Qué hace

- **Registro del día** (botón «Registrar»): la noche anterior, la mañana, los bloques de estudio, la tarde y cómo estás.
  Viene relleno con los hábitos de tu último registro y con las rutinas que marcaste («Tomar el sol» → luz solar,
  «Gimnasio» → entreno). Al guardar se marcan esas rutinas como hechas ese día.
- **Hoy**: cuatro semáforos (balance metabólico, codificación, sueño y termorregulación, rotación) y las alertas.
- **Reglas** (código, sin IA; umbrales en Ajustes): alerta circadiana, termorregulación, ilusión de competencia,
  sobrecarga, blindaje de dopamina, fatiga persistente y desajuste circadiano. Cada alerta se guarda con su fecha
  y crea **una** tarea en la categoría «Rendimiento» (si ya hay una pendiente de la misma regla, no se repite).
- **Semana / mes**, **Exámenes** (salen de los eventos de tipo «Examen» del Calendario: la asignatura es la sigla
  antes de « · ») y **Correlaciones** (a partir de 21 días).
- **Auditoría**: «Auditar hoy» crea la tarea «Prioridad de mañana»; «Auditar la semana» la guarda también como nota
  en «Rendimiento - Auditorías».
- **Exportar** (Ajustes → Tus datos): JSON con todo, o CSV de días y de bloques.

## Configurar la IA

1. Consigue al menos una clave gratuita y ponla en `.env`:

   | Variable | Dónde se saca |
   |---|---|
   | `OPENROUTER_API_KEY` | https://openrouter.ai/settings/keys |
   | `GROQ_API_KEY` | https://console.groq.com/keys |
   | `GEMINI_API_KEY` | https://aistudio.google.com/apikey |
   | `GITHUB_MODELS_TOKEN` | Token de GitHub con permiso `models:read` |

2. Reinicia el panel (`systemctl --user restart panel-maestro`). En Ajustes de Rendimiento → «Modelos de IA» verás
   cuáles tienen clave, su uso de hoy y si alguno está en pausa.

**La lista de modelos** está en `app/llm_modelos.json`, ordenada de mejor a peor. Para cambiarla, cópiala a
`data/llm_modelos.json` (esa copia manda y no se sube a git) y edítala: añadir un proveedor compatible con la API de
OpenAI es añadir un bloque con `base_url`, `modelo`, `clave_env` y, si quieres, `limite_dia`, `cuota` (modelos que
comparten límite), `timeout_s`, `json_mode` y `extra` (campos que se envían tal cual). `"activo": false` lo desactiva.
Los límites por defecto salen de la lista [free-llm-api-resources](https://github.com/cheahjs/free-llm-api-resources)
(copia generada el 21 de mayo de 2026; el repositorio original ya no está publicado): revísalos de vez en cuando.

**Respaldo**: se prueba cada modelo en orden. Un 429 lo deja en pausa (lo que diga `Retry-After`, o 10 min); un 5xx o
un timeout se reintenta con espera creciente; una respuesta vacía, un JSON roto o que no cumple el esquema pasan al
siguiente. Un modelo sin clave, en pausa o sin cuota hoy se salta. Si no repites nada y los datos no cambiaron, se
devuelve la auditoría guardada sin llamar a nadie (botón «Repetir» para forzarla).

**Privacidad**: solo se envían métricas de 7 días, con fechas relativas (d-6 … d0) y asignaturas como letras; la
nota libre, solo si activas «Incluir mi nota libre». OpenRouter recibe `provider.data_collection = "deny"`. Aun así,
los niveles gratuitos de algunos proveedores pueden usar lo que reciben para entrenar (Google, fuera de la UE/EEE/UK).
El registro (`logs/panel.log` y la tabla `llm_registro`) guarda modelo, latencia y tipo de error, nunca el contenido.

**Instrucciones**: el prompt del sistema se edita en la pestaña Auditoría; el formato JSON se añade siempre al final.

## Tests

```bash
venv/bin/python -m pytest tests/test_rendimiento.py tests/test_rendimiento_ia.py tests/test_llm_router.py
```

El router se prueba con `httpx.MockTransport` (429 con y sin `Retry-After`, timeout, 5xx, JSON no válido, respuesta
vacía, esquema malo, cuotas compartidas, sin claves): ningún test sale a la red.
