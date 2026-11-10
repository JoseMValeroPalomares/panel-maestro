"""
Router de LLM: una lista ORDENADA de modelos compatibles con la API de OpenAI (base_url + clave + modelo) y respaldo
automático. Independiente de quien lo use: la auditoría de rendimiento es solo el primer cliente.

Configuración: app/llm_modelos.json (por defecto, en el repo) o la copia editable de config.LLM_MODELS_FILE
(data/llm_modelos.json), que manda si existe. Las claves salen SIEMPRE de variables de entorno (`clave_env`).

    completar(mensajes, validar)   prueba los modelos en orden y devuelve el primero que pase `validar`
    estado()                       cada modelo: clave, uso de hoy, enfriamiento y última llamada (para Ajustes)

Política (Ajustes → IA, tabla ia_ajustes): por defecto SOLO modelos gratuitos que no entrenan con tus datos. Un modelo con
`entrena: true` solo entra si lo activas; uno con `pago: true`, solo si lo activas y dentro del presupuesto mensual
(`precio_in_1m`/`precio_out_1m` en USD por millón de tokens). Con `solo_privados` (nota sensible) únicamente modelos locales
o que no entrenan. `modelo_patrones` permite no fijar nombres: si `modelo` ya no está en el catálogo descubierto (`/models`,
en caché) se usa el primero que contenga algún patrón. `formato="texto"` devuelve {"texto": …} en vez de JSON.

Paso al siguiente modelo ante: 429 (y enfriamiento hasta Retry-After o `enfriamiento_429_s`), 5xx o timeout (tras
reintentar con backoff exponencial), 401/403/404/400, respuesta vacía, JSON no válido o que no cumple el esquema.
Un modelo sin clave, enfriándose o sin cuota hoy se salta sin llamarlo. Cada petición cuenta en su cuota del día
(`cuota` agrupa modelos que comparten límite, como los :free de OpenRouter). El registro guarda modelo, latencia y
tipo de error; nunca el contenido.
"""
import json
import os
import re
import time
from dataclasses import dataclass, field
from datetime import date
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Callable

import httpx

from app.database import get_db
from core import config
from core.logging_config import get_logger

log = get_logger("llm")
DEFAULT_FILE = Path(__file__).with_name("llm_modelos.json")
REGISTRO_MAX = 500


class LLMError(Exception):
    """Ningún modelo dio una respuesta válida (o no hay ninguno configurado)."""

    def __init__(self, mensaje: str, intentos: list[dict] | None = None, sin_claves: bool = False, cancelado: bool = False):
        super().__init__(mensaje)
        self.intentos = intentos or []
        self.sin_claves = sin_claves
        self.cancelado = cancelado


class _Fallo(Exception):
    def __init__(self, tipo: str, reintentable: bool = False, retry_after: float | None = None):
        super().__init__(tipo)
        self.tipo, self.reintentable, self.retry_after = tipo, reintentable, retry_after


@dataclass
class Resultado:
    datos: dict
    modelo_id: str
    proveedor: str
    modelo: str
    latencia_ms: int
    intentos: list[dict] = field(default_factory=list)
    tokens_in: int = 0
    tokens_out: int = 0
    coste: float = 0.0
    aviso: str | None = None


# ── Configuración ─────────────────────────────────────────────────────────────

def cargar_config() -> dict:
    ruta = config.LLM_MODELS_FILE if config.LLM_MODELS_FILE.is_file() else DEFAULT_FILE
    with open(ruta, encoding="utf-8") as f:
        cfg = json.load(f)
    modelos = []
    for m in cfg.get("modelos", []):
        if not m.get("id") or not m.get("base_url") or not m.get("modelo"):
            continue
        if m.get("activo", True) is False:
            continue
        if m.get("base_url_env") and os.environ.get(m["base_url_env"], "").strip():  # p. ej. OLLAMA_URL=http://192.168.1.50:11434
            u = os.environ[m["base_url_env"]].strip().rstrip("/")
            m = {**m, "base_url": u if u.endswith("/v1") else u + "/v1"}
        modelos.append(m)
    return {"max_intentos_total": int(cfg.get("max_intentos_total", 8)), "reintentos_por_modelo": int(cfg.get("reintentos_por_modelo", 2)),
            "enfriamiento_429_s": float(cfg.get("enfriamiento_429_s", 600)), "modelos": modelos, "archivo": str(ruta)}


def _clave(m: dict) -> str | None:
    env = m.get("clave_env")
    if m.get("local") and m.get("base_url_env") and not os.environ.get(m["base_url_env"], "").strip():
        return None  # Ollama solo cuenta si indicas dónde está (OLLAMA_URL)
    if not env:
        return "" if m.get("local") else None  # un modelo local no necesita clave
    return os.environ.get(env, "").strip() or None


def _cuota(m: dict) -> str:
    return m.get("cuota") or m["id"]


# ── Estado persistente (uso, enfriamiento, registro) ──────────────────────────

def _uso_hoy(conn, m: dict) -> int:
    r = conn.execute("SELECT peticiones FROM llm_uso WHERE cuota=? AND dia=?", (_cuota(m), date.today().isoformat())).fetchone()
    return r["peticiones"] if r else 0


def _contar(m: dict) -> None:
    with get_db() as conn:
        conn.execute("""INSERT INTO llm_uso (cuota, dia, peticiones) VALUES (?, ?, 1)
                        ON CONFLICT(cuota, dia) DO UPDATE SET peticiones = peticiones + 1""", (_cuota(m), date.today().isoformat()))


def _enfriar(m: dict, segundos: float, motivo: str, ahora: float) -> None:
    with get_db() as conn:
        conn.execute("INSERT INTO llm_enfriamiento (modelo, hasta, motivo) VALUES (?, ?, ?) ON CONFLICT(modelo) DO UPDATE SET hasta=excluded.hasta, motivo=excluded.motivo",
                     (m["id"], ahora + segundos, motivo))


def _registrar(m: dict, ok: bool, latencia_ms: int | None, error: str | None, ahora: float, tin: int = 0, tout: int = 0,
               coste: float = 0.0, uso: str = "rendimiento") -> None:
    """Solo modelo, latencia, tokens aproximados, coste y tipo de error: nunca el contenido."""
    log.info("LLM %s · %s · %s ms%s", m["id"], "ok" if ok else "fallo", latencia_ms if latencia_ms is not None else "-", f" · {error}" if error else "")
    with get_db() as conn:
        conn.execute("INSERT INTO llm_registro (at, modelo, ok, latencia_ms, error, tokens_in, tokens_out, coste, uso) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                     (ahora, m["id"], int(ok), latencia_ms, error, tin, tout, coste, uso))
        conn.execute("DELETE FROM llm_registro WHERE id <= (SELECT MAX(id) FROM llm_registro) - ?", (REGISTRO_MAX,))


# ── Política (Ajustes) ────────────────────────────────────────────────────────

POLITICA_DEFECTO = {"permitir_entrenan": False, "permitir_pago": False, "presupuesto_mes": 0.0, "categorias_sensibles": []}


def leer_politica() -> dict:
    with get_db() as conn:
        filas = {r["clave"]: r["valor"] for r in conn.execute("SELECT clave, valor FROM ia_ajustes")}
    p = dict(POLITICA_DEFECTO)
    for k, v in filas.items():
        if k in p:
            try:
                p[k] = json.loads(v)
            except ValueError:
                pass
    return p


def guardar_politica(cambios: dict) -> dict:
    with get_db() as conn:
        for k, v in cambios.items():
            if k in POLITICA_DEFECTO:
                conn.execute("INSERT INTO ia_ajustes (clave, valor) VALUES (?, ?) ON CONFLICT(clave) DO UPDATE SET valor=excluded.valor",
                             (k, json.dumps(v)))
    return leer_politica()


def gasto_mes(ahora: float | None = None) -> float:
    d = date.fromtimestamp(ahora or time.time()).replace(day=1)
    desde = time.mktime(d.timetuple())
    with get_db() as conn:
        r = conn.execute("SELECT COALESCE(SUM(coste), 0) AS c FROM llm_registro WHERE at >= ? AND ok = 1", (desde,)).fetchone()
    return float(r["c"])


# ── Catálogo de modelos (descubrimiento) ──────────────────────────────────────

def _catalogo(url: str) -> list[str]:
    with get_db() as conn:
        r = conn.execute("SELECT modelos FROM ia_catalogo WHERE url=?", (url,)).fetchone()
    try:
        return json.loads(r["modelos"]) if r else []
    except ValueError:
        return []


def modelo_efectivo(m: dict) -> str:
    """El modelo configurado, o (si ya no está en el catálogo descubierto) el primero que case con `modelo_patrones`."""
    pats = [p.lower() for p in m.get("modelo_patrones") or []]
    if not pats:
        return m["modelo"]
    cat = _catalogo(m["base_url"])
    if not cat or m["modelo"] in cat:
        return m["modelo"]
    suf = m.get("sufijo", "")
    for p in pats:  # en el orden de preferencia de los patrones
        for c in cat:
            if p in c.lower() and c.endswith(suf):
                return c
    return m["modelo"]


def descubrir(transport: httpx.BaseTransport | None = None, solo_si_antiguo_s: float | None = None) -> dict:
    """Pide GET {base_url}/models a cada proveedor con clave y guarda la lista en caché. Devuelve {base_url: nº o error}."""
    res: dict[str, object] = {}
    vistos: set[str] = set()
    with httpx.Client(transport=transport) as c:
        for m in cargar_config()["modelos"]:
            url = m["base_url"]
            if url in vistos or _clave(m) is None:
                continue
            vistos.add(url)
            if solo_si_antiguo_s is not None:
                with get_db() as conn:
                    r = conn.execute("SELECT at FROM ia_catalogo WHERE url=?", (url,)).fetchone()
                if r and time.time() - r["at"] < solo_si_antiguo_s:
                    continue
            try:
                h = {"Authorization": f"Bearer {_clave(m)}"} if _clave(m) else {}
                r = c.get(url.rstrip("/") + "/models", headers=h, timeout=15)
                if r.status_code != 200:
                    res[url] = f"{r.status_code}"
                    continue
                datos = r.json()
                ids = sorted({(x.get("id") or x.get("name") or "").removeprefix("models/") for x in (datos.get("data") or datos.get("models") or []) if isinstance(x, dict)} - {""})
                with get_db() as conn:
                    conn.execute("INSERT INTO ia_catalogo (url, modelos, at) VALUES (?, ?, ?) ON CONFLICT(url) DO UPDATE SET modelos=excluded.modelos, at=excluded.at",
                                 (url, json.dumps(ids), time.time()))
                res[url] = len(ids)
            except (httpx.HTTPError, ValueError) as e:
                res[url] = type(e).__name__
    return res


def estado(ahora: float | None = None) -> dict:
    ahora = ahora or time.time()
    cfg = cargar_config()
    pol = leer_politica()
    out = []
    mes = time.mktime(date.fromtimestamp(ahora).replace(day=1).timetuple())
    with get_db() as conn:
        for m in cfg["modelos"]:
            enf = conn.execute("SELECT hasta, motivo FROM llm_enfriamiento WHERE modelo=?", (m["id"],)).fetchone()
            ult = conn.execute("SELECT at, ok, latencia_ms, error FROM llm_registro WHERE modelo=? ORDER BY id DESC LIMIT 1", (m["id"],)).fetchone()
            err = conn.execute("SELECT at, error FROM llm_registro WHERE modelo=? AND ok=0 ORDER BY id DESC LIMIT 1", (m["id"],)).fetchone()
            tok = conn.execute("SELECT COALESCE(SUM(tokens_in + tokens_out), 0) AS t, COALESCE(SUM(coste), 0) AS c FROM llm_registro WHERE modelo=? AND at>=? AND ok=1",
                               (m["id"], mes)).fetchone()
            out.append({"id": m["id"], "proveedor": m.get("proveedor", ""), "modelo": m["modelo"], "modelo_efectivo": modelo_efectivo(m),
                        "clave_env": m.get("clave_env"), "clave": _clave(m) is not None, "local": bool(m.get("local")),
                        "entrena": bool(m.get("entrena")), "pago": bool(m.get("pago")),
                        "uso_hoy": _uso_hoy(conn, m), "limite_dia": m.get("limite_dia") or None,
                        "tokens_mes": tok["t"], "coste_mes": round(tok["c"], 4),
                        "enfriado_hasta": enf["hasta"] if enf and enf["hasta"] > ahora else None, "motivo": enf["motivo"] if enf and enf["hasta"] > ahora else None,
                        "ultima": dict(ult) if ult else None, "ultimo_error": dict(err) if err else None})
    archivo = Path(cfg["archivo"])
    try:  # relativa al proyecto si está dentro: más corta y sin rutas de la máquina
        archivo = archivo.resolve().relative_to(config.PROJECT_ROOT)
    except ValueError:
        pass
    return {"archivo": str(archivo), "modelos": out, "configurados": sum(1 for x in out if x["clave"]),
            "politica": pol, "gasto_mes": round(gasto_mes(ahora), 4)}


# ── Llamada ───────────────────────────────────────────────────────────────────

def _retry_after(resp: httpx.Response) -> float | None:
    v = resp.headers.get("retry-after")
    if not v:
        return None
    try:
        return max(1.0, float(v))
    except ValueError:
        try:
            return max(1.0, parsedate_to_datetime(v).timestamp() - time.time())
        except (TypeError, ValueError):
            return None


def extraer_json(texto: str) -> dict:
    """El JSON de la respuesta, aunque venga entre ```json … ``` o con texto alrededor."""
    t = (texto or "").strip()
    if not t:
        raise _Fallo("respuesta vacía")
    t = re.sub(r"^```(?:json)?\s*|\s*```$", "", t)
    try:
        v = json.loads(t)
    except ValueError:
        i, j = t.find("{"), t.rfind("}")
        if i < 0 or j <= i:
            raise _Fallo("JSON no válido")
        try:
            v = json.loads(t[i:j + 1])
        except ValueError:
            raise _Fallo("JSON no válido")
    if not isinstance(v, dict):
        raise _Fallo("JSON no válido")
    return v


def estimar_tokens(texto: str) -> int:
    """Aproximación (≈ 3,5 caracteres por token en español); basta para cuotas y presupuesto."""
    return max(1, int(len(texto) / 3.5))


def _llamar(cliente: httpx.Client, m: dict, clave: str, mensajes: list[dict], temperatura: float, formato: str = "json",
            max_salida: int | None = None) -> tuple[str, dict, str | None]:
    body = {"model": modelo_efectivo(m), "messages": mensajes, "temperature": temperatura, **(m.get("extra") or {})}
    if m.get("json_mode") and formato == "json":
        body["response_format"] = {"type": "json_object"}
    if max_salida:
        body["max_tokens"] = max_salida
    headers = {"Content-Type": "application/json"}
    if clave:
        headers["Authorization"] = f"Bearer {clave}"
    try:
        r = cliente.post(m["base_url"].rstrip("/") + "/chat/completions", json=body, headers=headers, timeout=float(m.get("timeout_s", 60)))
    except httpx.TimeoutException:
        raise _Fallo("timeout", reintentable=True)
    except httpx.TransportError:
        raise _Fallo("sin conexión")
    if r.status_code == 429:
        raise _Fallo("429 límite", retry_after=_retry_after(r))
    if r.status_code >= 500:
        raise _Fallo(f"{r.status_code} error del servidor", reintentable=True)
    if r.status_code >= 400:
        raise _Fallo(f"{r.status_code} rechazado")
    try:
        datos = r.json()
        ch = datos["choices"][0]
        return ch["message"].get("content") or "", datos.get("usage") or {}, ch.get("finish_reason")
    except (ValueError, KeyError, IndexError, TypeError, AttributeError):
        raise _Fallo("respuesta sin formato OpenAI")


def _motivo_omitido(m: dict, pol: dict, solo_privados: bool, tin: int, tout: int, gastado: float) -> tuple[str | None, float]:
    """Por qué un modelo no se puede usar con esta política (o None) y su coste estimado."""
    if m.get("entrena") and not pol["permitir_entrenan"]:
        return "puede entrenar con tus datos (desactivado en Ajustes)", 0.0
    if m.get("entrena") and solo_privados:
        return "nota sensible: este proveedor puede entrenar", 0.0
    if m.get("pago"):
        if not pol["permitir_pago"]:
            return "de pago (desactivado en Ajustes)", 0.0
        coste = tin * float(m.get("precio_in_1m", 0)) / 1e6 + tout * float(m.get("precio_out_1m", 0)) / 1e6
        if not pol["presupuesto_mes"] or gastado + coste > pol["presupuesto_mes"]:
            return "superaría el presupuesto mensual", coste
        return None, coste
    lim = m.get("max_entrada_tokens")
    if lim and tin > lim:
        return f"la nota no cabe en su límite de {lim} tokens", 0.0
    return None, 0.0


def completar(mensajes: list[dict], validar: Callable[[dict], dict] | None = None, *, temperatura: float = 0.3,
              transport: httpx.BaseTransport | None = None, dormir: Callable[[float], None] = time.sleep,
              reloj: Callable[[], float] = time.time, formato: str = "json", max_salida: int | None = None,
              solo_privados: bool = False, politica: dict | None = None, cancelado: Callable[[], bool] | None = None,
              uso: str = "rendimiento", excluir: set[str] | None = None, solo: str | None = None) -> Resultado:
    """Prueba los modelos en orden. `validar(datos)` devuelve los datos limpios o lanza ValueError (→ siguiente modelo).
    `formato="texto"`: datos = {"texto": respuesta}. `excluir`: ids ya descartados (p. ej. tras un reintento estricto)."""
    cfg = cargar_config()
    pol = {**POLITICA_DEFECTO, **(politica or leer_politica())}
    intentos: list[dict] = []
    total = 0
    modelos = [m for m in cfg["modelos"] if (solo is None or m["id"] == solo)]
    con_clave = [m for m in modelos if _clave(m) is not None]
    if not con_clave:
        raise LLMError("No hay ningún modelo de IA con clave: añade OPENROUTER_API_KEY, GROQ_API_KEY, GEMINI_API_KEY, "
                       "MISTRAL_API_KEY o GITHUB_MODELS_TOKEN a .env (o activa un modelo local con Ollama).", sin_claves=True)
    tin = estimar_tokens(" ".join(x.get("content", "") for x in mensajes))
    tout = max_salida or 1500
    gastado = gasto_mes(reloj())
    with httpx.Client(transport=transport) as cliente:
        for m in con_clave:
            if total >= cfg["max_intentos_total"]:
                break
            if cancelado and cancelado():
                raise LLMError("Cancelado", intentos, cancelado=True)
            if excluir and m["id"] in excluir:
                continue
            motivo, coste_est = _motivo_omitido(m, pol, solo_privados, tin, tout, gastado)
            if motivo:
                intentos.append({"modelo": m["id"], "error": motivo, "omitido": True})
                continue
            ahora = reloj()
            with get_db() as conn:
                enf = conn.execute("SELECT hasta FROM llm_enfriamiento WHERE modelo=?", (m["id"],)).fetchone()
                usado = _uso_hoy(conn, m)
            if enf and enf["hasta"] > ahora:
                intentos.append({"modelo": m["id"], "error": "en enfriamiento"})
                continue
            if m.get("limite_dia") and usado >= m["limite_dia"]:
                intentos.append({"modelo": m["id"], "error": "cuota del día agotada"})
                continue
            cat = _catalogo(m["base_url"])
            if cat and modelo_efectivo(m) not in cat:  # los gratuitos rotan: no se llama a un modelo que ya no existe
                intentos.append({"modelo": m["id"], "error": "el modelo ya no existe en el proveedor (se elige solo al actualizar el catálogo)"})
                continue
            for n in range(max(1, cfg["reintentos_por_modelo"])):
                if total >= cfg["max_intentos_total"]:
                    break
                if cancelado and cancelado():
                    raise LLMError("Cancelado", intentos, cancelado=True)
                total += 1
                t0 = reloj()
                _contar(m)
                try:
                    texto, u, fin = _llamar(cliente, m, _clave(m), mensajes, temperatura, formato, max_salida)
                    if fin == "length":
                        raise _Fallo("respuesta cortada por el límite de tokens")
                    datos = extraer_json(texto) if formato == "json" else {"texto": texto}
                    if formato == "texto" and not texto.strip():
                        raise _Fallo("respuesta vacía")
                    if validar:
                        try:
                            datos = validar(datos)
                        except ValueError as e:
                            raise _Fallo(f"esquema no válido: {str(e)[:120]}")
                except _Fallo as f:
                    ms = int((reloj() - t0) * 1000)
                    _registrar(m, False, ms, f.tipo, reloj(), uso=uso)
                    intentos.append({"modelo": m["id"], "error": f.tipo})
                    if f.tipo.startswith("429"):
                        _enfriar(m, f.retry_after or cfg["enfriamiento_429_s"], "429", reloj())
                        break
                    if f.reintentable and n + 1 < cfg["reintentos_por_modelo"]:
                        dormir(min(30.0, 2.0 ** n))  # 1 s, 2 s, 4 s…
                        continue
                    break
                ms = int((reloj() - t0) * 1000)
                ti = int(u.get("prompt_tokens") or tin)
                to = int(u.get("completion_tokens") or estimar_tokens(texto))
                coste = (ti * float(m.get("precio_in_1m", 0)) + to * float(m.get("precio_out_1m", 0))) / 1e6 if m.get("pago") else 0.0
                _registrar(m, True, ms, None, reloj(), ti, to, coste, uso)
                aviso = None
                if m.get("pago") and pol["presupuesto_mes"] and gastado + coste >= 0.8 * pol["presupuesto_mes"]:
                    aviso = f"Llevas {gastado + coste:.2f} $ de {pol['presupuesto_mes']:.2f} $ del presupuesto mensual de IA."
                return Resultado(datos, m["id"], m.get("proveedor", ""), modelo_efectivo(m), ms, intentos, ti, to, coste, aviso)
    raise LLMError("Ningún modelo de IA dio una respuesta válida. Lo demás sigue funcionando; prueba más tarde.", intentos)


def probar(modelo_id: str, transport: httpx.BaseTransport | None = None) -> dict:
    """Una petición mínima a un modelo concreto (botón «Probar» de Ajustes). No cuenta como política: es explícita."""
    m = next((x for x in cargar_config()["modelos"] if x["id"] == modelo_id), None)
    if not m:
        raise LLMError("Ese modelo no existe en la configuración")
    if _clave(m) is None:
        raise LLMError(f"Falta la clave {m.get('clave_env')} en .env", sin_claves=True)
    t0 = time.time()
    try:
        with httpx.Client(transport=transport) as c:
            _llamar(c, m, _clave(m), [{"role": "user", "content": "Responde solo: ok"}], 0, "texto", 16)
    except _Fallo as f:
        _registrar(m, False, int((time.time() - t0) * 1000), f.tipo, time.time(), uso="prueba")
        return {"ok": False, "error": f.tipo}
    _registrar(m, True, int((time.time() - t0) * 1000), None, time.time(), uso="prueba")
    return {"ok": True, "latencia_ms": int((time.time() - t0) * 1000), "modelo": modelo_efectivo(m)}


def cadena(politica: dict | None = None, solo_privados: bool = False, tin: int = 0, tout: int = 1500) -> list[dict]:
    """Los modelos con clave, en orden, cada uno con `omitido` (motivo por el que la política no lo deja usar) o None."""
    pol = {**POLITICA_DEFECTO, **(politica or leer_politica())}
    gastado = gasto_mes()
    out = []
    for m in cargar_config()["modelos"]:
        if _clave(m) is None:
            continue
        motivo, _ = _motivo_omitido(m, pol, solo_privados, tin, tout, gastado)
        out.append({"id": m["id"], "proveedor": m.get("proveedor", ""), "modelo": modelo_efectivo(m), "omitido": motivo})
    return out
