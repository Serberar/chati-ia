import contextlib
import re
import time
import uuid
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken

from infra import paths

MEDIA_TYPES = {".png": "image/png", ".jpg": "image/jpeg", ".webp": "image/webp",
               ".mp4": "video/mp4", ".wav": "audio/wav"}
NAME_RE = re.compile(r"[0-9a-f]{32}\.(png|jpg|webp|mp4|wav)")
TMP_MAX_AGE_SECONDS = 60 * 60


def media_dir() -> Path:
    d = paths.OUTPUT_DIR / "media"
    d.mkdir(parents=True, exist_ok=True)
    return d


def tmp_dir() -> Path:
    d = paths.OUTPUT_DIR / "_tmp"
    d.mkdir(parents=True, exist_ok=True)
    return d


def url_for(name: str) -> str:
    return f"/media/{name}"


def valid_name(name: str) -> bool:
    return bool(NAME_RE.fullmatch(name or ""))


def save(data: bytes, ext: str, dek: bytes) -> str:
    ext = ext if ext.startswith(".") else "." + ext
    if ext not in MEDIA_TYPES:
        raise ValueError(f"Tipo de archivo no soportado: {ext}")
    name = uuid.uuid4().hex + ext
    (media_dir() / (name + ".enc")).write_bytes(Fernet(dek).encrypt(data))
    return name


def save_file(path: Path, dek: bytes) -> str:
    try:
        return save(path.read_bytes(), path.suffix.lower(), dek)
    finally:
        path.unlink(missing_ok=True)


def load(name: str, dek: bytes) -> bytes | None:
    if not valid_name(name):
        return None
    enc = media_dir() / (name + ".enc")
    if not enc.exists():
        return None
    try:
        return Fernet(dek).decrypt(enc.read_bytes())
    except InvalidToken:
        return None


def delete(name: str) -> None:
    if valid_name(name):
        (media_dir() / (name + ".enc")).unlink(missing_ok=True)


def media_type(name: str) -> str:
    return MEDIA_TYPES.get(Path(name).suffix.lower(), "application/octet-stream")


@contextlib.contextmanager
def plain_copy(data: bytes, ext: str):
    path = tmp_dir() / (uuid.uuid4().hex + (ext if ext.startswith(".") else "." + ext))
    path.write_bytes(data)
    try:
        yield path
    finally:
        path.unlink(missing_ok=True)


def new_tmp_path(ext: str) -> Path:
    return tmp_dir() / (uuid.uuid4().hex + (ext if ext.startswith(".") else "." + ext))


MEDIA_MAX_AGE_DAYS = 30


def cleanup_old_media(max_age_days: float = MEDIA_MAX_AGE_DAYS) -> int:
    removed = 0
    limit = time.time() - max_age_days * 86400
    for p in media_dir().glob("*.enc"):
        try:
            if p.stat().st_mtime < limit:
                p.unlink()
                removed += 1
        except OSError:
            pass
    return removed


def cleanup_tmp(max_age: float = TMP_MAX_AGE_SECONDS) -> int:
    removed = 0
    limit = time.time() - max_age
    for p in tmp_dir().iterdir():
        try:
            if p.is_file() and p.stat().st_mtime < limit:
                p.unlink()
                removed += 1
        except OSError:
            pass
    return removed
