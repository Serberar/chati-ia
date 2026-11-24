import hashlib
import json
import os
import re
import time

import requests

from infra.paths import DATA_DIR, MODELS_DIR
from version import VERSION

LATEST_URL = "https://api.github.com/repos/Serberar/chati-ia/releases/latest"
TOKEN_FILE = MODELS_DIR.parent / "secretos" / "github_token.txt"
NO_TOKEN = "Falta la clave de GitHub de este ordenador (Opciones > Buscar actualizaciones)."
ASSET_NAME = "ChatiIA-Instalador.exe"
CACHE_PATH = DATA_DIR / "app_update.json"
CACHE_TTL_SECONDS = 6 * 60 * 60
DOWNLOAD_DIR = DATA_DIR / "updates"


class UpdateError(Exception):
    pass


def _parse(version: str) -> tuple[int, ...]:
    return tuple(int(n) for n in re.findall(r"\d+", version)[:3])


def is_newer(latest: str, current: str) -> bool:
    return _parse(latest) > _parse(current)


def set_token(token: str) -> None:
    TOKEN_FILE.parent.mkdir(parents=True, exist_ok=True)
    TOKEN_FILE.write_text(token.strip(), encoding="utf-8")


def has_token() -> bool:
    return TOKEN_FILE.is_file() and bool(TOKEN_FILE.read_text(encoding="utf-8").strip())


def _headers(accept: str) -> dict:
    if not has_token():
        raise ValueError(NO_TOKEN)
    return {"Accept": accept, "Authorization": f"Bearer {TOKEN_FILE.read_text(encoding='utf-8').strip()}"}


def _fetch_latest() -> dict:
    resp = requests.get(LATEST_URL, timeout=10, headers=_headers("application/vnd.github+json"))
    if resp.status_code in (401, 404):
        raise ValueError("GitHub no acepta la clave de este ordenador: pon otra en Opciones > Buscar actualizaciones.")
    resp.raise_for_status()
    release = resp.json()
    asset = next((a for a in release.get("assets", []) if a.get("name") == ASSET_NAME), {})
    return {
        "version": str(release.get("tag_name", "")).lstrip("v"),
        "notes": release.get("body") or "",
        "url": asset.get("url"),
        "sha256": (asset.get("digest") or "").removeprefix("sha256:").lower(),
    }


def _installable(latest: dict) -> bool:
    return bool(latest["url"] and latest["sha256"] and is_newer(latest["version"], VERSION))


def check(force: bool = False) -> dict:
    latest = None
    if not force and CACHE_PATH.exists():
        try:
            cached = json.loads(CACHE_PATH.read_text(encoding="utf-8"))
            if time.time() - cached["checked_at"] < CACHE_TTL_SECONDS:
                latest = cached["latest"]
        except (ValueError, KeyError):
            pass
    if latest is None:
        try:
            latest = _fetch_latest()
        except (requests.RequestException, ValueError) as exc:
            return {"current": VERSION, "latest": None, "available": False, "notes": "", "error": str(exc),
                    "falta_clave": not has_token()}
        CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
        CACHE_PATH.write_text(json.dumps({"checked_at": time.time(), "latest": latest}, ensure_ascii=False),
                              encoding="utf-8")
    return {"current": VERSION, "latest": latest["version"], "available": _installable(latest),
            "notes": latest["notes"], "error": None}


def _download(url: str, sha256: str, target) -> None:
    partial = target.with_suffix(".part")
    digest = hashlib.sha256()
    try:
        with requests.get(url, stream=True, timeout=60, headers=_headers("application/octet-stream")) as resp:
            resp.raise_for_status()
            with open(partial, "wb") as out:
                for chunk in resp.iter_content(1 << 20):
                    out.write(chunk)
                    digest.update(chunk)
    except requests.RequestException as exc:
        partial.unlink(missing_ok=True)
        raise UpdateError(f"No se pudo descargar la version nueva: {exc}") from exc
    if digest.hexdigest() != sha256:
        partial.unlink(missing_ok=True)
        raise UpdateError("El instalador descargado no coincide con el publicado en GitHub. No se instala.")
    os.replace(partial, target)


def install() -> str:
    try:
        latest = _fetch_latest()
    except (requests.RequestException, ValueError) as exc:
        raise UpdateError(f"No se pudo consultar GitHub: {exc}") from exc
    if not _installable(latest):
        raise UpdateError(f"No hay ninguna version mas nueva que la {VERSION}.")
    DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)
    for old in DOWNLOAD_DIR.iterdir():
        old.unlink(missing_ok=True)
    target = DOWNLOAD_DIR / f"ChatiIA-Instalador-{latest['version']}.exe"
    _download(latest["url"], latest["sha256"], target)
    try:
        os.startfile(str(target), "open", "/SILENT /SUPPRESSMSGBOXES /NORESTART /UPDATE=1")
    except OSError as exc:
        raise UpdateError(f"No se pudo abrir el instalador: {exc}") from exc
    return latest["version"]
