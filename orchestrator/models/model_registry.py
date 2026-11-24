from dataclasses import dataclass
from pathlib import Path

from infra.paths import MODELS_DIR

IMG_DIR = MODELS_DIR / "img"
VID_DIR = MODELS_DIR / "vid"

IMAGE_ARCHITECTURES = {
    "sdxl": {"comfy_dir": "checkpoints", "label": "SDXL", "extensions": (".safetensors",)},
    "sd15": {"comfy_dir": "checkpoints", "label": "SD 1.5", "extensions": (".safetensors",)},
    "flux": {"comfy_dir": "diffusion_models", "label": "FLUX", "extensions": (".safetensors", ".gguf")},
}

VIDEO_ARCHITECTURES = {
    "ltxv": {"comfy_dir": "checkpoints", "label": "LTX-Video", "extensions": (".safetensors",)},
    "wan": {"comfy_dir": "diffusion_models", "label": "Wan 2.2", "extensions": (".safetensors", ".gguf")},
}


@dataclass
class ModelEntry:
    id: str
    architecture: str
    architecture_label: str
    label: str
    comfy_path: str


def _scan(base_dir: Path, architectures: dict) -> list[ModelEntry]:
    entries = []
    for arch, meta in architectures.items():
        arch_dir = base_dir / meta["comfy_dir"] / arch
        if not arch_dir.exists():
            continue
        for f in sorted(arch_dir.iterdir()):
            if not f.is_file() or f.suffix.lower() not in meta["extensions"]:
                continue
            entries.append(ModelEntry(
                id=f"{arch}:{f.stem}",
                architecture=arch,
                architecture_label=meta["label"],
                label=f.stem,
                comfy_path=str(Path(arch) / f.name),
            ))
    return entries


def list_image_models() -> list[ModelEntry]:
    return _scan(IMG_DIR, IMAGE_ARCHITECTURES)


def list_video_models() -> list[ModelEntry]:
    return _scan(VID_DIR, VIDEO_ARCHITECTURES)


def get_image_model(model_id: str | None) -> ModelEntry | None:
    models = list_image_models()
    if not models:
        return None
    if model_id:
        return next((m for m in models if m.id == model_id), None)
    return next((m for m in models if m.architecture == "flux"), models[0])


def get_video_model(model_id: str | None) -> ModelEntry | None:
    models = list_video_models()
    if not models:
        return None
    if model_id:
        return next((m for m in models if m.id == model_id), None)
    return next((m for m in models if m.architecture == "wan"), models[0])


def image_model_folder(architecture: str) -> Path | None:
    meta = IMAGE_ARCHITECTURES.get(architecture)
    if not meta:
        return None
    return IMG_DIR / meta["comfy_dir"] / architecture


def video_model_folder(architecture: str) -> Path | None:
    meta = VIDEO_ARCHITECTURES.get(architecture)
    if not meta:
        return None
    return VID_DIR / meta["comfy_dir"] / architecture


def image_model_path(model_id: str) -> Path | None:
    entry = get_image_model(model_id)
    if entry is None:
        return None
    return image_model_folder(entry.architecture) / Path(entry.comfy_path).name


def video_model_path(model_id: str) -> Path | None:
    entry = get_video_model(model_id)
    if entry is None:
        return None
    return video_model_folder(entry.architecture) / Path(entry.comfy_path).name


def list_image_architectures() -> list[dict]:
    installed = _scan(IMG_DIR, IMAGE_ARCHITECTURES)
    return [
        {
            "id": arch,
            "label": meta["label"],
            "folder": str(image_model_folder(arch)),
            "installed_count": sum(1 for m in installed if m.architecture == arch),
        }
        for arch, meta in IMAGE_ARCHITECTURES.items()
    ]


def list_video_architectures() -> list[dict]:
    installed = list_video_models()
    return [
        {
            "id": arch,
            "label": meta["label"],
            "folder": str(video_model_folder(arch)),
            "installed_count": sum(1 for m in installed if m.architecture == arch),
        }
        for arch, meta in VIDEO_ARCHITECTURES.items()
    ]
