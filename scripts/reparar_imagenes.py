"""
Rehace las imágenes automáticas del Baúl (canales de YouTube) y de los platos de Comidas.

    python -m scripts.reparar_imagenes --baul --platos            # aplica
    python -m scripts.reparar_imagenes --baul --platos --simular  # solo dice qué haría

- Baúl: cada canal de YouTube toma su avatar real (y su nombre, si el título era el identificador de la URL);
  un canal que ya no existe se queda sin imagen (la interfaz pinta el icono de YouTube). Los vídeos sin miniatura
  local la recuperan de img.youtube.com.
- Platos: los que tienen una foto de stock de la siembra (image_source «unsplash»/«pexels»), una foto remota o
  ninguna, reciben la primera foto que encuentre una búsqueda de imágenes por su nombre. Las fotos puestas a mano
  (image_source «manual» o «busqueda») no se tocan salvo con --todos-los-platos.

Escribe en las BDs configuradas (.env / PANEL_*): haz antes una copia. Las fotos quedan en static/uploads/thumbs.
"""
import argparse
import re
import time

from app.scraper import _extract_channel_handle, _extract_youtube_id, cache_thumbnail, search_images, youtube_channel_info
from core import config

THUMBS = str(config.UPLOADS_DIR / "thumbs")
AUTOMATICAS = ("unsplash", "pexels", "")


def _es_canal(url: str) -> bool:
    return bool(re.search(r"youtube\.com/(@|channel/|c/|user/)", url or ""))


def reparar_baul(simular: bool) -> None:
    from app.database import get_db
    with get_db() as conn:
        rows = [dict(r) for r in conn.execute("SELECT id, url, title, channel, image FROM resources WHERE url LIKE '%youtu%'")]
    cambios = sin_canal = 0
    for r in rows:
        nuevo = {}
        if _es_canal(r["url"]):
            info = youtube_channel_info(r["url"])
            time.sleep(0.5)
            if info.get("image"):
                local = "" if simular else cache_thumbnail(info["image"], THUMBS)
                if local or simular:
                    nuevo["image"] = local or info["image"]
            elif not info:
                nuevo["image"] = ""  # canal borrado o ilegible: mejor el icono que una foto inventada
                sin_canal += 1
            auto = {_extract_channel_handle(r["url"]) or "", "www.youtube.com", "youtube.com"}
            if info.get("title") and (r["title"] in auto or not r["title"]):
                nuevo["title"] = nuevo["channel"] = info["title"]
        else:
            vid = _extract_youtube_id(r["url"])
            if vid and not (r["image"] or "").startswith("/static/"):
                local = "" if simular else cache_thumbnail(f"https://img.youtube.com/vi/{vid}/hqdefault.jpg", THUMBS)
                if local or simular:
                    nuevo["image"] = local or "(miniatura del vídeo)"
        nuevo = {k: v for k, v in nuevo.items() if v != r.get(k)}
        if not nuevo:
            continue
        cambios += 1
        print(f"  Baúl {r['id']:>3} {r['url'][:60]:<60} → {', '.join(f'{k}={str(v)[:50]}' for k, v in nuevo.items())}")
        if not simular:
            with get_db() as conn:
                conn.execute(f"UPDATE resources SET {', '.join(f'{k}=?' for k in nuevo)} WHERE id=?", (*nuevo.values(), r["id"]))
    print(f"Baúl: {cambios} de {len(rows)} recursos de YouTube cambian ({sin_canal} canales ya no existen)")


def reparar_platos(simular: bool, todos: bool) -> None:
    from comidas.database import get_db
    with get_db() as conn:
        rows = [dict(r) for r in conn.execute("SELECT id, nombre, image_url, image_source FROM meals ORDER BY id")]
    pendientes = [r for r in rows if todos or (r["image_source"] or "") in AUTOMATICAS or not (r["image_url"] or "").startswith("/static/")]
    hechos, fallidos = 0, []
    for i, r in enumerate(pendientes, 1):
        opciones = search_images(f"{r['nombre']} plato receta", n=6)
        if not opciones:  # sin resultados o el buscador pide calma: un reintento con pausa
            time.sleep(20)
            opciones = search_images(f"{r['nombre']} plato receta", n=6)
        elegida = ""
        for o in opciones:
            elegida = o["image"] if simular else cache_thumbnail(o["image"], THUMBS)
            if elegida:
                break
        if elegida:
            hechos += 1
            print(f"  [{i}/{len(pendientes)}] {r['nombre'][:40]:<40} → {elegida[:70]}")
            if not simular:
                with get_db() as conn:
                    conn.execute("UPDATE meals SET image_url=?, image_source='busqueda' WHERE id=?", (elegida, r["id"]))
        else:
            fallidos.append(r["nombre"])
            print(f"  [{i}/{len(pendientes)}] {r['nombre'][:40]:<40} → sin foto (se queda como estaba)")
        time.sleep(1.2)
    print(f"Platos: {hechos} de {len(pendientes)} con foto nueva" + (f"; sin foto: {', '.join(fallidos)}" if fallidos else ""))


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--baul", action="store_true", help="canales y vídeos de YouTube del Baúl")
    ap.add_argument("--platos", action="store_true", help="fotos de los platos de Comidas")
    ap.add_argument("--todos-los-platos", action="store_true", help="también los platos con foto puesta a mano")
    ap.add_argument("--simular", action="store_true", help="no escribe nada: solo dice qué haría")
    a = ap.parse_args()
    if not (a.baul or a.platos):
        ap.error("indica --baul, --platos o los dos")
    if a.baul:
        reparar_baul(a.simular)
    if a.platos:
        reparar_platos(a.simular, a.todos_los_platos)


if __name__ == "__main__":
    main()
