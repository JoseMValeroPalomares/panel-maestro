# IA para corregir notas — investigación y decisiones

Investigación hecha el **2026-11-10** con la documentación oficial de cada proveedor cuando fue accesible
(rate-limits de [Groq](https://console.groq.com/docs/rate-limits), [OpenRouter](https://openrouter.ai/docs/api-reference/limits),
[Cerebras](https://inference-docs.cerebras.ai/support/rate-limits), [Google AI Studio](https://aistudio.google.com/docs/rate-limits))
y comparativas de terceros para lo que las páginas oficiales no detallan
([OpenRouter blog](https://openrouter.ai/blog/tutorials/free-llm-apis-compared/), [DEV](https://dev.to/unicodefawn/free-llm-api-tiers-in-2026-the-actual-rate-limits-and-why-they-keep-changing),
[Requesty](https://www.requesty.ai/blog/free-llm-apis)). **Los límites cambian cada pocas semanas**: por eso el código no los fija
(salvo `limite_dia` orientativo en `app/llm_modelos.json`, editable) y los modelos se descubren con `GET /models`.

## Comparación

| Proveedor | Modelos gratis (hoy) | Límites gratuitos | Contexto | Español | ¿Entrena con tus datos? | Coste |
|---|---|---|---|---|---|---|
| **OpenRouter** (`:free`) | rota: variantes gratuitas de gpt-oss, Llama, etc. | 20 RPM, **50 peticiones/día** (1000 con ≥ 10 $ comprados) (oficial) | según modelo | Bueno | Depende del proveedor final; con `provider.data_collection: deny` se excluyen los que entrenan | Gratis |
| **GitHub Models** | gpt-4.1-mini y otros | ~150 peticiones/día, entrada ≤ ~8K tokens | 8K en gratis | Muy bueno | No para entrenar según condiciones de GitHub | Gratis (con token `models:read`) |
| **Groq** | `gpt-oss-120b`, `gpt-oss-20b`, `qwen3.8-27b` | 30 RPM, 1000/día, **8K tokens/min**, 200K/día (oficial) | 128K | Bueno | No entrena por defecto | Gratis |
| **Google Gemini (AI Studio)** | Gemini 2.x/3 Flash, Gemma | 5–15 RPM, 20–1500/día según modelo (ver AI Studio) | hasta 1M | Muy bueno | **Sí** en el nivel gratuito (fuera de UE/EEE/UK según terceros: verificar) | Gratis |
| **Mistral (Experiment)** | Mistral Large/Medium | ~1.000 M tokens/mes | 128K | Muy bueno | **Sí: hay que aceptar entrenamiento** para el plan gratuito | Gratis |
| **Ollama local** (sobremesa) | el que descargues (Qwen, Gemma, Llama…) | sin límite; velocidad según GPU | según modelo | Bueno–regular (depende del tamaño) | **Nunca sale de tu red** | Gratis (electricidad) |
| **Anthropic API** | Claude Sonnet/Haiku | de pago | 200K+ | Excelente | No entrena con API por defecto | **De pago** (la suscripción Pro no incluye API) |

## Decisión: cadena y orden

1. ~~Cerebras~~ — **descartado (2026-11-10)**: pide método de pago y solo da 5 $ de crédito que caducan; no es gratuito de verdad.
2. **OpenRouter `:free`** con `data_collection: deny` — respaldo variado, pero solo 50 peticiones/día.
3. **GitHub Models** — buen español, límite de entrada pequeño (notas cortas).
4. **Groq** — rapidísimo, pero 8K TPM: solo notas cortas (`max_entrada_tokens: 3000`).
5. **Gemini** y 6. **Mistral** — buena calidad pero **entrenan**: apagados salvo que los actives en Ajustes → IA, y nunca con notas sensibles.
7. **Ollama** — último recurso gratuito y el único para notas sensibles si los demás fallan; requiere `OLLAMA_URL` en `.env`.
8. **Sin modelos de pago**: se quitó Anthropic de la cadena (decisión del usuario); todo es gratuito.

El orden sale de: (1) que no entrene, (2) cuota gratuita fiable y documentada, (3) calidad en español. Se puede reordenar
copiando `app/llm_modelos.json` a `data/llm_modelos.json`; `scripts/evaluar_modelos.py` puntúa cada modelo con las mismas reglas de
validación sobre notas sintéticas para decidir con datos.

## Mecanismos anti-degradación

- Toda respuesta pasa por `app/ia_validacion.py` (fórmulas, tablas, bloques, enlaces, etiquetas, longitud, números…). Si falla: un reintento
  estricto con el mismo modelo y, si vuelve a fallar, el siguiente. La nota muestra qué modelo corrigió y el historial acumula el recuento.
- 429 → modelo en enfriamiento hasta `Retry-After`; cuota diaria propia por proveedor; 5xx/timeouts con backoff.
- Descubrimiento: `GET {base_url}/models` (cache 24 h en `ia_catalogo`). Si el modelo configurado desaparece, se usa el primero que
  case con `modelo_patrones`.

## Incertidumbres (revisar)

- Condiciones de datos de Cerebras, GitHub Models y Gemini en la UE: las páginas oficiales no las detallaban en el momento de la
  consulta; se confirmaron solo con fuentes secundarias. Por prudencia, Gemini y Mistral están marcados como «entrenan».
- Precios de Anthropic en `llm_modelos.json` (`precio_in_1m`/`precio_out_1m`) son estimaciones: ajústalos a la tarifa vigente.

## Contexto pequeño (Groq, GitHub Models)
La guía, el prompt y la lista de títulos ocupan ≈ 2 000 tokens en cada petición. Para que las notas largas quepan, `app/ia_notas.py:dividir` las parte por encabezados (sin cortar bloques de código) y se corrigen trozo a trozo; al final todo el conjunto se vuelve a validar. Gemini (1 M de contexto) y Mistral van enteras, pero entrenan: solo si los activas en Ajustes.
