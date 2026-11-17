"""Direcciones de este equipo, del ESP32 y de la extensión, tal como las conoce el panel (core/red.py).

    python -m scripts.red                 lo que hay guardado y lo que se ve ahora
    python -m scripts.red --redetectar    busca la placa (mDNS, última IP, vecinos, respaldo, barrido) y lo guarda
    python -m scripts.red --json          lo mismo, en JSON (para otros scripts)

Lee y escribe el mismo `red.json` que el panel (en `PANEL_DATA_DIR`); no cambia nada de la red ni del router.
"""

import argparse
import json
import sys
import time

from core import red


def _hace(ts: float | None) -> str:
    if not ts:
        return "nunca"
    s = max(0, int(time.time() - ts))
    return f"hace {s} s" if s < 90 else f"hace {s // 60} min" if s < 5400 else f"hace {s // 3600} h"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Red y dispositivos del panel")
    ap.add_argument("--redetectar", action="store_true", help="buscar la placa ahora")
    ap.add_argument("--json", action="store_true", help="salida en JSON")
    args = ap.parse_args(argv)

    res = red.detectar_esp32() if args.redetectar else None
    e = red.estado()
    if args.json:
        print(json.dumps({"resultado": res, **e}, ensure_ascii=False, indent=2))
        return 0 if res is None or res["ok"] else 1

    s, p, x = e["servidor"], e["esp32"], e["extension"]
    print(f"Este equipo  {s['nombre']}: {', '.join(s['ips']) or 'sin red local'} (reserva {s['respaldo']})")
    for u in s["urls"]:
        print(f"             {u['url']}  · {u['donde']}")
    if not p["configurada"]:
        print("ESP32        sin placa (pon ESP32_HOST=auto en .env)")
    else:
        origen = "fijada a mano" if p["manual"] else p.get("origen") or "sin comprobar"
        print(f"ESP32        {p['direccion']} ({origen}) · MAC {p.get('mac') or '?'} · visto {_hace(p.get('visto'))}")
        print(f"             reserva {p['respaldo']} · {p['nombre_mdns']}")
    if res is not None:
        if res["ok"]:
            print(f"             ✓ contesta en {res['ip']} (por {res['origen']})")
        else:
            print(f"             ✗ no contesta; probadas: {', '.join(d for _, d in res['probadas']) or 'ninguna'}")
    if x["conocida"]:
        vigente = "" if x["url_vigente"] else "  ← dirección antigua"
        print(
            f"Extensión    {x.get('version') or '?'} por {x.get('url') or '?'} · vista {_hace(x.get('visto'))}{vigente}"
        )
    else:
        print("Extensión    aún no ha llamado a este panel")
    return 0 if res is None or res["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
