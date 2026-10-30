"""
scraper.py — Extrae metadatos (título, descripción, imagen) de una URL.

Estrategia:
  1. YouTube → parsea directamente la URL del vídeo/canal para obtener
     thumbnail sin necesidad de API key (usa oEmbed público).
  2. Resto de webs → descarga la página y lee las etiquetas Open Graph
     y <title> / <meta description> con BeautifulSoup.

Dependencias necesarias (añadir a requirements.txt):
    httpx
    beautifulsoup4
    lxml
"""

import ipaddress
import re
import socket
import httpx
from bs4 import BeautifulSoup
from urllib.parse import urlparse, urljoin, quote
from ddgs import DDGS

from core.logging_config import get_logger

log = get_logger("scraper")

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (compatible; DigitalBrainBot/1.0; "
        "+https://github.com/JoseMValeroPalomares/panel-maestro)"
    )
}
TIMEOUT = 10  # segundos
MAX_REDIRECTS = 5
MAX_BODY_BYTES = 2 * 1024 * 1024  # no descargamos más de 2 MB de HTML


# ──────────────────────────────────────────────────────────────
# PROTECCIÓN SSRF
# ──────────────────────────────────────────────────────────────
# El scraper descarga URLs que escribe el usuario. Sin filtro, alguien con
# acceso podría usarlo para sondear la red local (router, ESP32,
# 127.0.0.1:8000/api/...) o metadatos de nube. Solo se permiten URLs
# http(s) cuyo host resuelva EXCLUSIVAMENTE a IPs públicas, y cada salto
# de redirección se vuelve a validar.
# Riesgo residual conocido: DNS rebinding entre la validación y la
# conexión (httpx vuelve a resolver). Mitigado parcialmente al validar
# cada redirección; para un panel personal en LAN es aceptable.

class UnsafeURLError(ValueError):
    pass


def _ip_is_public(ip_str: str) -> bool:
    ip = ipaddress.ip_address(ip_str)
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped:
        ip = ip.ipv4_mapped
    return ip.is_global and not ip.is_multicast


def validate_public_url(url: str) -> str:
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise UnsafeURLError("Solo se permiten URLs http(s)")
    host = parsed.hostname
    if not host:
        raise UnsafeURLError("URL sin host")
    try:
        port = parsed.port or (443 if parsed.scheme == "https" else 80)
    except ValueError:
        raise UnsafeURLError("Puerto no válido")
    try:
        infos = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    except socket.gaierror:
        raise UnsafeURLError("No se pudo resolver el host")
    addresses = {info[4][0] for info in infos}
    if not addresses or not all(_ip_is_public(a) for a in addresses):
        raise UnsafeURLError("El host apunta a una dirección privada o reservada")
    return url


def safe_get(url: str, max_bytes: int = MAX_BODY_BYTES, strict: bool = False) -> tuple[httpx.Response, bytes]:
    """GET con validación SSRF en cada salto y tope de tamaño de respuesta.
    Con strict=True, superar el tope es un error (imágenes); si no, se trunca (HTML)."""
    current = url
    with httpx.Client(timeout=TIMEOUT, headers=HEADERS, follow_redirects=False) as client:
        for _ in range(MAX_REDIRECTS + 1):
            validate_public_url(current)
            with client.stream("GET", current) as r:
                if r.is_redirect:
                    location = r.headers.get("location")
                    if not location:
                        raise UnsafeURLError("Redirección sin destino")
                    current = urljoin(current, location)
                    continue
                r.raise_for_status()
                chunks, total = [], 0
                for chunk in r.iter_bytes():
                    total += len(chunk)
                    if total > max_bytes:
                        if strict:
                            raise UnsafeURLError("La respuesta supera el tamaño máximo")
                        break
                    chunks.append(chunk)
                return r, b"".join(chunks)
    raise UnsafeURLError("Demasiadas redirecciones")


def _http_url_or_empty(value: str) -> str:
    """Las imágenes se pintan en <img src>: solo aceptamos http(s) absolutas."""
    value = (value or "").strip()
    return value if re.match(r"^https?://", value, re.IGNORECASE) else ""


# ──────────────────────────────────────────────────────────────
# YOUTUBE
# ──────────────────────────────────────────────────────────────

def _is_youtube(url: str) -> bool:
    return bool(re.search(r'(youtube\.com|youtu\.be)', url))


def _is_youtube_channel(url: str) -> bool:
    """Detecta si la URL es un canal (no un vídeo concreto)."""
    return bool(re.search(r'youtube\.com/(@[\w.-]+|channel/|c/|user/)', url))


def _extract_channel_handle(url: str) -> str | None:
    """
    Extrae el nombre del canal directamente de la URL, sin necesidad de
    scraping. Para '/@codemath1' devuelve 'codemath1'.
    Para '/c/Nombre' o '/user/Nombre' devuelve 'Nombre'.
    """
    m = re.search(r'youtube\.com/@([\w.-]+)', url)
    if m:
        return m.group(1)
    m = re.search(r'youtube\.com/(?:c|user)/([\w.-]+)', url)
    if m:
        return m.group(1)
    return None


def _search_channel_logo_image(channel_name: str) -> str:
    """
    Busca "<nombre del canal> youtube channel logo" en imágenes y
    devuelve la primera URL encontrada. No es tan fiable como sacar el
    avatar real del canal (para nombres poco conocidos puede traer
    ruido), pero es mucho más robusto que pelearse con el muro de
    consentimiento de YouTube o con el HTML interno de un buscador.
    """
    query = f"{channel_name} youtube channel logo"
    try:
        with DDGS() as ddgs:
            results = list(ddgs.images(query, max_results=1))
            if results:
                return _http_url_or_empty(results[0].get("image", ""))
    except Exception:
        pass
    return ""



def _youtube_channel_metadata(url: str) -> dict:
    handle = _extract_channel_handle(url)
    title = handle if handle else _hostname(url)
    avatar = _search_channel_logo_image(title)
    return {
        "title": title,
        "description": "Canal de YouTube",
        "image": avatar,
        "resource_type": "youtube",
        "channel": title,
    }

    

def _youtube_metadata(url: str) -> dict:
    """
    Para vídeos usa la API oEmbed pública de YouTube (sin API key).
    Para canales, extrae el handle directamente de la URL (ver
    _youtube_channel_metadata) en vez de fiarse del <title> de la
    página, que YouTube no siempre devuelve correctamente sin sesión.
    """
    if _is_youtube_channel(url):
        return _youtube_channel_metadata(url)

    oembed_url = f"https://www.youtube.com/oembed?url={quote(url, safe='')}&format=json"
    try:
        with httpx.Client(timeout=TIMEOUT, headers=HEADERS, follow_redirects=True) as client:
            r = client.get(oembed_url)
            if r.status_code == 200:
                data = r.json()
                video_id = _extract_youtube_id(url)
                thumb = (
                    f"https://img.youtube.com/vi/{video_id}/hqdefault.jpg"
                    if video_id
                    else data.get("thumbnail_url", "")
                )
                return {
                    "title": data.get("title", ""),
                    "description": f"Canal: {data.get('author_name', '')}",
                    "image": thumb,
                    "resource_type": "youtube",
                    "channel": data.get("author_name", ""),
                }
    except Exception:
        pass

    # Fallback: no es un vídeo reconocible ni un canal con handle claro
    return _web_metadata(url, force_type="youtube")


def _extract_youtube_id(url: str) -> str | None:
    """Extrae el video ID de distintos formatos de URL de YouTube."""
    patterns = [
        r'v=([A-Za-z0-9_-]{11})',
        r'youtu\.be/([A-Za-z0-9_-]{11})',
        r'embed/([A-Za-z0-9_-]{11})',
        r'shorts/([A-Za-z0-9_-]{11})',
    ]
    for p in patterns:
        m = re.search(p, url)
        if m:
            return m.group(1)
    return None


# ──────────────────────────────────────────────────────────────
# WEB GENÉRICA (Open Graph + fallbacks)
# ──────────────────────────────────────────────────────────────

def _web_metadata(url: str, force_type: str = "web") -> dict:
    try:
        r, body = safe_get(url)
    except UnsafeURLError as e:
        log.warning("URL rechazada por el scraper (%s): %s", e, url)
        return {
            "title": _hostname(url),
            "description": f"No se descargaron metadatos: {e}",
            "image": "",
            "resource_type": force_type,
        }
    except Exception:
        return {
            "title": _hostname(url),
            "description": "No se pudo cargar la página",
            "image": "",
            "resource_type": force_type,
        }

    content_type = r.headers.get("content-type", "")
    if content_type and not any(t in content_type for t in ("html", "xml")):
        return {"title": _hostname(url), "description": "", "image": "", "resource_type": force_type}

    soup = BeautifulSoup(body.decode(r.encoding or "utf-8", errors="replace"), "lxml")

    def og(prop):
        tag = soup.find("meta", property=f"og:{prop}")
        if tag:
            return tag.get("content", "").strip()
        return ""

    def meta_name(name):
        tag = soup.find("meta", attrs={"name": name})
        if tag:
            return tag.get("content", "").strip()
        return ""

    title = (
        og("title")
        or meta_name("twitter:title")
        or ((soup.title.string or "").strip() if soup.title else "")
        or _hostname(url)
    )
    description = (
        og("description")
        or meta_name("description")
        or meta_name("twitter:description")
        or ""
    )[:300]  # Truncamos para no guardar párrafos enteros

    image = (
        og("image")
        or meta_name("twitter:image")
        or _favicon(soup, url)
        or ""
    )

    image = _http_url_or_empty(urljoin(str(r.url), image)) if image else ""

    return {
        "title": title[:500],
        "description": description,
        "image": image,
        "resource_type": force_type,
    }


def _hostname(url: str) -> str:
    try:
        return urlparse(url).hostname or url
    except Exception:
        return url


def _favicon(soup: BeautifulSoup, url: str) -> str:
    """Intenta sacar el favicon como imagen de fallback."""
    # Google favicon service como último recurso
    return f"https://www.google.com/s2/favicons?domain={urlparse(url).netloc}&sz=128"


# ──────────────────────────────────────────────────────────────
# FUNCIÓN PÚBLICA
# ──────────────────────────────────────────────────────────────

def fetch_metadata(url: str) -> dict:
    """
    Punto de entrada principal. Devuelve un dict con:
        title, description, image, resource_type
    """
    url = url.strip()
    if _is_youtube(url):
        return _youtube_metadata(url)
    return _web_metadata(url)


# ──────────────────────────────────────────────────────────────
# CACHÉ LOCAL DE MINIATURAS
# ──────────────────────────────────────────────────────────────
# Las miniaturas se descargan una vez (con la misma protección SSRF), se
# verifican con Pillow y se guardan como WebP pequeñas en uploads/thumbs.
# Así el Baúl no depende de servidores de terceros (bloqueos CORP, 429,
# rastreo) y funciona sin conexión.

THUMB_MAX_BYTES = 12 * 1024 * 1024
THUMB_WIDTH = 480


def _sized_image_url(url: str) -> str:
    """Pide a los CDN conocidos una versión pequeña en vez del original de varios MB."""
    if url.startswith("https://images.unsplash.com/"):
        base = url.split("?", 1)[0]
        return f"{base}?w={THUMB_WIDTH * 2}&q=80&auto=format&fit=crop"
    return url


def cache_thumbnail(image_url: str, thumbs_dir) -> str:
    """Devuelve la URL local (/static/uploads/thumbs/...) o "" si no se pudo."""
    import hashlib
    import io
    import os
    import warnings

    from PIL import Image

    image_url = _http_url_or_empty(image_url)
    if not image_url:
        return ""
    name = hashlib.sha256(image_url.encode()).hexdigest()[:32] + ".webp"
    os.makedirs(thumbs_dir, exist_ok=True)
    target = os.path.join(thumbs_dir, name)
    if os.path.exists(target):
        return f"/static/uploads/thumbs/{name}"
    try:
        r, body = safe_get(_sized_image_url(image_url), max_bytes=THUMB_MAX_BYTES, strict=True)
        if not body:
            return ""
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(body)) as img:
                img.load()
                if img.width * img.height > 40_000_000:
                    return ""
                img = img.convert("RGBA" if img.mode in ("RGBA", "LA", "P") else "RGB")
                if img.width > THUMB_WIDTH:
                    img = img.resize((THUMB_WIDTH, max(1, round(img.height * THUMB_WIDTH / img.width))), Image.LANCZOS)
                # temporal + cambio de golpe: un corte a mitad dejaría una miniatura rota para siempre (ya «existe»)
                img.save(target + ".tmp", "WEBP", quality=78, method=4)
                os.replace(target + ".tmp", target)
        return f"/static/uploads/thumbs/{name}"
    except Exception as e:  # imagen inválida, URL privada, timeout…
        log.info("No se pudo cachear la miniatura %s: %s", image_url, e)
        return ""
