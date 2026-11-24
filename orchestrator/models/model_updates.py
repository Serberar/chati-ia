import json
import logging
import os
import time
from pathlib import Path

import requests

from infra.paths import DATA_DIR

_logger = logging.getLogger(__name__)

REGISTRY_BASE = "https://registry.ollama.ai/v2/library"
CACHE_PATH = DATA_DIR / "model_updates.json"
CACHE_TTL_SECONDS = 24 * 60 * 60


def _models_dir() -> Path:
    return Path(os.environ.get("OLLAMA_MODELS", str(Path.home() / ".ollama" / "models")))


def _library_dir() -> Path:
    return _models_dir() / "manifests" / "registry.ollama.ai" / "library"


def is_installed(name: str, tag: str) -> bool:
    return any((_models_dir() / layout / "library" / name / tag).is_file()
               for layout in ("manifests/registry.ollama.ai", "manifests-v2/ollama.com"))


def installed_official_models() -> list[tuple[str, str]]:
    library_dir = _library_dir()
    if not library_dir.exists():
        return []
    found = []
    for name_dir in sorted(library_dir.iterdir()):
        if not name_dir.is_dir():
            continue
        for tag_file in sorted(name_dir.iterdir()):
            if tag_file.is_file():
                found.append((name_dir.name, tag_file.name))
    return found


def _model_layer_digest(manifest: dict) -> str | None:
    for layer in manifest.get("layers", []):
        if layer.get("mediaType") == "application/vnd.ollama.image.model":
            return layer.get("digest")
    return None


def local_digest(name: str, tag: str) -> str | None:
    path = _library_dir() / name / tag
    if not path.exists():
        return None
    manifest = json.loads(path.read_text(encoding="utf-8"))
    return _model_layer_digest(manifest)


def remote_digest(name: str, tag: str, timeout: int = 10) -> str | None:
    resp = requests.get(f"{REGISTRY_BASE}/{name}/manifests/{tag}", timeout=timeout)
    resp.raise_for_status()
    return _model_layer_digest(resp.json())


def _check_one(name: str, tag: str) -> dict:
    model_id = f"{name}:{tag}"
    if tag.endswith(("-cpu", "-mixto")):
        return {"model": model_id, "update_available": False, "error": None, "local_only": True}
    local = local_digest(name, tag)
    try:
        remote = remote_digest(name, tag)
        return {
            "model": model_id,
            "update_available": bool(local and remote and local != remote),
            "error": None,
        }
    except Exception as exc:
        return {"model": model_id, "update_available": False, "error": str(exc)}


def check_updates(force: bool = False) -> list[dict]:
    if not force and CACHE_PATH.exists():
        try:
            cached = json.loads(CACHE_PATH.read_text(encoding="utf-8"))
            if time.time() - cached.get("checked_at_epoch", 0) < CACHE_TTL_SECONDS:
                return cached["results"]
        except (json.JSONDecodeError, KeyError):
            _logger.debug("check_updates: se sigue sin ello", exc_info=True)

    results = [_check_one(name, tag) for name, tag in installed_official_models()]

    CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    CACHE_PATH.write_text(
        json.dumps({"checked_at_epoch": time.time(), "results": results}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return results
