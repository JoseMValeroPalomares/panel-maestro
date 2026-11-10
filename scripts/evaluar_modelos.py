"""
Evalúa cada modelo configurado con las notas SINTÉTICAS de tests/fixtures/ia (nunca tus notas) y las mismas reglas de
validación que usa «Corregir con IA». Sirve para comparar y reordenar la cadena con datos.

    python -m scripts.evaluar_modelos                 # todos los modelos con clave
    python -m scripts.evaluar_modelos --modelo cerebras-gpt-oss-120b --json

Puntuación por modelo: notas válidas / notas, latencia media y problemas más comunes. Usa PANEL_DISABLE_* no hace falta:
solo llama a los proveedores (las notas de prueba salen a la red; son inventadas). Ignora la política de «entrenan» y de
pago A PROPÓSITO para poder compararlos: evita pasar `--incluir-pago` si no quieres gastar.
"""
import argparse
import json
import sys
import time
from collections import Counter
from pathlib import Path

from app import ia_notas, ia_validacion, llm_router

FIXTURES = Path(__file__).resolve().parent.parent / "tests" / "fixtures" / "ia"
TITULOS = {"nota-inicial": "Nota inicial"}


def evaluar(modelo: dict, notas: dict[str, str], transport=None) -> dict:
    ok, lat, fallos = 0, [], Counter()
    detalle = {}
    for nombre, texto in notas.items():
        problemas: list[str] = []

        def validar(d):
            t = ia_validacion.quitar_envoltorio(d["texto"])
            problemas[:] = ia_validacion.validar(texto, t, TITULOS)
            if problemas:
                raise ValueError("; ".join(problemas[:3]))
            return {"texto": t}
        t0 = time.time()
        try:
            llm_router.completar(ia_notas._mensajes(texto, TITULOS), validar, temperatura=0.2, formato="texto", solo=modelo["id"], uso="evaluacion",
                                 politica={"permitir_entrenan": True, "permitir_pago": modelo.get("pago", False) and "--incluir-pago" in sys.argv,
                                           "presupuesto_mes": 1.0, "categorias_sensibles": []}, transport=transport, dormir=lambda s: None)
            ok += 1
            detalle[nombre] = "ok"
            lat.append(time.time() - t0)
        except llm_router.LLMError as e:
            motivo = (e.intentos[-1]["error"] if e.intentos else str(e))
            detalle[nombre] = motivo
            fallos[motivo[:70]] += 1
    return {"modelo": modelo["id"], "validas": ok, "total": len(notas), "puntuacion": round(ok / len(notas), 2),
            "latencia_media_s": round(sum(lat) / len(lat), 1) if lat else None, "fallos": dict(fallos), "detalle": detalle}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--modelo")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--incluir-pago", action="store_true")
    a = ap.parse_args()
    notas = {p.stem: p.read_text(encoding="utf-8") for p in sorted(FIXTURES.glob("*.md"))}
    modelos = [m for m in llm_router.cargar_config()["modelos"] if llm_router._clave(m) is not None and (not a.modelo or m["id"] == a.modelo)
               and (not m.get("pago") or a.incluir_pago)]
    if not modelos:
        print("Ningún modelo con clave configurada (o es de pago: usa --incluir-pago).", file=sys.stderr)
        return 1
    res = sorted((evaluar(m, notas) for m in modelos), key=lambda r: (-r["puntuacion"], r["latencia_media_s"] or 999))
    if a.json:
        print(json.dumps(res, ensure_ascii=False, indent=2))
    else:
        print(f"{'modelo':34} {'válidas':>8} {'lat. media':>11}  fallos")
        for r in res:
            print(f"{r['modelo']:34} {r['validas']:>3}/{r['total']:<4} {str(r['latencia_media_s']) + ' s':>11}  {r['fallos'] or ''}")
        print("\nOrden sugerido:", " > ".join(r["modelo"] for r in res))
    return 0


if __name__ == "__main__":
    sys.exit(main())
