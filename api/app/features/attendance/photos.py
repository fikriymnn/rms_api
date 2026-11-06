import io
import time
import uuid
from pathlib import Path

from PIL import Image, UnidentifiedImageError

from app.core.config import settings
from app.core.errors import BadRequest, NotFound

MAX_UPLOAD = 2 * 1024 * 1024
MAX_PIXELS = 12_000_000


def save_photo(raw: bytes, outlet_id: str) -> str:
    """Validasi bahwa ini JPEG sungguhan, tulis ulang (buang metadata), kembalikan path relatif."""
    if len(raw) > MAX_UPLOAD:
        raise BadRequest("Foto terlalu besar (maks. 2 MB)")
    try:
        img = Image.open(io.BytesIO(raw))
        if img.format != "JPEG":
            raise BadRequest("Foto harus berformat JPEG")
        if img.width * img.height > MAX_PIXELS:
            raise BadRequest("Resolusi foto terlalu besar")
        img.load()
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError):
        raise BadRequest("File bukan gambar yang valid") from None
    img = img.convert("RGB")
    img.thumbnail((480, 480))
    rel = f"{outlet_id}/{time.strftime('%Y%m')}/{uuid.uuid4().hex}.jpg"
    path = resolve(rel)
    path.parent.mkdir(parents=True, exist_ok=True)
    img.save(path, "JPEG", quality=80)  # menyimpan ulang = EXIF/GPS bawaan foto hilang
    return rel


def resolve(rel: str) -> Path:
    base = Path(settings.photo_dir).resolve()
    path = (base / rel).resolve()
    if not path.is_relative_to(base):
        raise NotFound("Foto tidak ditemukan")
    return path


def delete_photo(rel: str | None) -> None:
    if not rel:
        return
    try:
        resolve(rel).unlink(missing_ok=True)
    except OSError:
        pass
