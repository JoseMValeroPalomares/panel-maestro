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


def safe_get(url: str, max_bytes: int = MAX_BODY_BYTES, strict: bool = False, headers: dict | None = None,
             cookies: dict | None = None) -> tuple[httpx.Response, bytes]:
    """GET con validación SSRF en cada salto y tope de tamaño de respuesta.
    Con strict=True, superar el tope es un error (imágenes); si no, se trunca (HTML)."""
    current = url
    with httpx.Client(timeout=TIMEOUT, headers=headers or HEADERS, cookies=cookies, follow_redirects=False) as client:
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


# La página de un canal trae su avatar real y su nombre en las etiquetas Open Graph. Con la cookie SOCS=CAI (solo las
# necesarias) YouTube no enseña el muro de consentimiento de la UE; con un navegador «normal» devuelve la página
# completa. Antes se buscaba «<canal> youtube channel logo» en un buscador de imágenes, que traía cualquier cosa.
YT_HEADERS = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36",
    "Accept-Language": "es-ES,es;q=0.9,en;q=0.6",
}
YT_COOKIES = {"SOCS": "CAI"}


def _og_tags(html: str) -> dict:
    """og:title, og:image… de un HTML. Con una expresión regular sobre todo el texto: YouTube las pone tras un
    «</head>» que aparece antes dentro de un script, y parsear 2 MB para cuatro etiquetas no compensa."""
    import html as htmllib
    out = {}
    for prop, content in re.findall(r'<meta\s+property="og:([\w:]+)"\s+content="([^"]*)"', html):
        out.setdefault(prop, htmllib.unescape(content).strip())
    return out


def youtube_channel_info(url: str) -> dict:
    """{"title", "image"} reales de un canal, o {} si no se pudo (canal borrado, sin red…)."""
    try:
        _r, body = safe_get(url, headers=YT_HEADERS, cookies=YT_COOKIES)
    except Exception as e:
        log.info("No se pudo leer el canal %s: %s", url, e)
        return {}
    og = _og_tags(body.decode("utf-8", errors="replace"))
    image = _http_url_or_empty(og.get("image", ""))
    # el avatar viene a 900 px: con 240 basta y pesa una fracción
    image = re.sub(r"=s\d+(-)", r"=s240\1", image) if "googleusercontent.com" in image else image
    return {"title": og.get("title", ""), "image": image} if (image or og.get("title")) else {}


def _youtube_channel_metadata(url: str) -> dict:
    handle = _extract_channel_handle(url)
    info = youtube_channel_info(url)
    title = info.get("title") or handle or _hostname(url)
    return {
        "title": title,
        "description": "Canal de YouTube",
        "image": info.get("image", ""),  # sin imagen, la interfaz dibuja el icono de YouTube (nunca una foto inventada)
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


_YT_HOST = re.compile(r"^(?:www\.|m\.|music\.)?(?:youtube\.com|youtube-nocookie\.com)$|^youtu\.be$", re.IGNORECASE)


def youtube_video_id(url: str) -> str | None:
    """ID de 11 caracteres de un vídeo de YouTube, sea cual sea la forma de la URL (watch?v=…&list=…, youtu.be/…, shorts/,
    live/, embed/, music.youtube.com…). None si no es una URL de vídeo de YouTube (un canal, una lista sin vídeo, otra web…)."""
    from urllib.parse import parse_qs, urlparse
    try:
        u = urlparse(url.strip())
    except ValueError:
        return None
    if not _YT_HOST.match(u.hostname or ""):
        return None
    if (u.hostname or "").lower() == "youtu.be":
        cand = u.path.lstrip("/").split("/")[0]
    else:
        m = re.match(r"^/(?:shorts|live|embed|v)/([\w-]{11})(?:/|$)", u.path)
        cand = m.group(1) if m else (parse_qs(u.query).get("v") or [""])[0] if u.path.rstrip("/") == "/watch" else ""
    return cand if re.fullmatch(r"[\w-]{11}", cand or "") else None


def canonical_youtube_url(video_id: str) -> str:
    return f"https://www.youtube.com/watch?v={video_id}"


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


def search_images(query: str, n: int = 8) -> list[dict]:
    """Candidatas de una búsqueda de imágenes (DuckDuckGo): [{"image", "thumbnail", "width", "height", "title"}].
    Solo fotos http(s) razonables: ni iconos diminutos, ni tiras alargadas, ni SVG/GIF."""
    try:
        with DDGS() as ddgs:
            raw = list(ddgs.images(query, region="es-es", safesearch="moderate", max_results=max(n * 3, 15)))
    except Exception as e:
        log.info("Búsqueda de imágenes fallida (%s): %s", query, e)
        return []
    out = []
    for r in raw:
        img = _http_url_or_empty(r.get("image", ""))
        w, h = int(r.get("width") or 0), int(r.get("height") or 0)
        if not img or re.search(r"\.(svg|gif)(\?|$)", img, re.I) or w < 400 or h < 300 or not (0.7 <= w / h <= 2.2):
            continue
        out.append({"image": img, "thumbnail": _http_url_or_empty(r.get("thumbnail", "")), "width": w, "height": h,
                    "title": (r.get("title") or "")[:200]})
        if len(out) >= n:
            break
    return out


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
