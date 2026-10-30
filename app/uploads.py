"""Subida de imágenes (pegar con Ctrl+V en el editor)."""
import io
import os
import uuid
import warnings

from fastapi import APIRouter, File, HTTPException, UploadFile
from PIL import Image

from core import config
from core.logging_config import get_logger

router = APIRouter()
log = get_logger("cerebro")
UPLOADS_DIR = str(config.UPLOADS_DIR)


# El tipo real se decide por el CONTENIDO (Pillow), nunca por la cabecera del cliente.
ALLOWED_IMAGE_FORMATS = {"PNG": ".png", "JPEG": ".jpg", "GIF": ".gif", "WEBP": ".webp"}
MAX_UPLOAD_BYTES = 10 * 1024 * 1024
MAX_IMAGE_PIXELS = 40_000_000  # ~ 8000x5000; por encima se trata como bomba de descompresión


def verify_image_bytes(data: bytes) -> str:
    """Devuelve la extensión segura si `data` es una imagen válida permitida;
    lanza HTTPException(400) en cualquier otro caso."""
    if not data:
        raise HTTPException(status_code=400, detail="Archivo vacío")
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(data)) as img:
                fmt = img.format
                width, height = img.size
                img.verify()  # detecta archivos truncados/corruptos
    except (Image.DecompressionBombError, Image.DecompressionBombWarning):
        raise HTTPException(status_code=400, detail="Imagen demasiado grande")
    except Exception:
        raise HTTPException(status_code=400, detail="El archivo no es una imagen válida")
    if fmt not in ALLOWED_IMAGE_FORMATS:
        raise HTTPException(status_code=400, detail="Formato de imagen no permitido (PNG, JPEG, GIF o WEBP)")
    if width * height > MAX_IMAGE_PIXELS:
        raise HTTPException(status_code=400, detail="Imagen demasiado grande")
    return ALLOWED_IMAGE_FORMATS[fmt]


@router.post("/api/upload-image")
async def upload_image(image: UploadFile = File(...)):
    data = await image.read(MAX_UPLOAD_BYTES + 1)
    if len(data) > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="La imagen supera los 10 MB")
    ext = verify_image_bytes(data)
    os.makedirs(UPLOADS_DIR, exist_ok=True)
    filename = f"{uuid.uuid4().hex}{ext}"
    with open(os.path.join(UPLOADS_DIR, filename), "wb") as f:
        f.write(data)
    log.info("Imagen subida: %s (%d bytes)", filename, len(data))
    return {"url": f"/static/uploads/{filename}"}
