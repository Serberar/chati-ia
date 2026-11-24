import json
import time
from pathlib import Path

from agents.comfyui_client import submit_and_wait, upload_unique
from media import content_guard
from models import model_registry

WORKFLOW_PATH = Path(__file__).parent.parent / "workflows" / "flux_image.json"
SDXL_WORKFLOW_PATH = Path(__file__).parent.parent / "workflows" / "sdxl_image.json"
UPSCALE_WORKFLOW_PATH = Path(__file__).parent.parent / "workflows" / "upscale_image.json"

_CHECKPOINT_PLACEHOLDER_BY_ARCH = {"flux": "__UNET_PATH__"}


class NoModelInstalledError(Exception):
    pass


class ImageAgent:
    def __init__(self, base_url: str):
        self.base_url = base_url.rstrip("/")
        self.template = json.loads(WORKFLOW_PATH.read_text(encoding="utf-8"))
        self.sdxl_template = json.loads(SDXL_WORKFLOW_PATH.read_text(encoding="utf-8"))
        self.upscale_template = json.loads(UPSCALE_WORKFLOW_PATH.read_text(encoding="utf-8"))

    def generate(self, prompt: str, width: int = 1024, height: int = 1024, timeout: int = 480,
                 model_id: str | None = None) -> bytes:
        content_guard.check(prompt)
        entry = model_registry.get_image_model(model_id)
        if entry is None:
            raise NoModelInstalledError(
                "No hay ningun modelo de imagen instalado. Añade uno en "
                f"{model_registry.IMG_DIR} (ver Opciones > Modelos > Imagen)."
            )
        template = self.template if entry.architecture == "flux" else self.sdxl_template
        placeholder = _CHECKPOINT_PLACEHOLDER_BY_ARCH.get(entry.architecture, "__CHECKPOINT_PATH__")

        seed = int(time.time() * 1000) % (2**32)
        raw = json.dumps(template)
        raw = raw.replace(f'"{placeholder}"', json.dumps(entry.comfy_path))
        raw = raw.replace('"__PROMPT__"', json.dumps(prompt))
        raw = raw.replace('"__WIDTH__"', str(width))
        raw = raw.replace('"__HEIGHT__"', str(height))
        raw = raw.replace('"__SEED__"', str(seed))
        workflow = json.loads(raw)
        return submit_and_wait(self.base_url, workflow, "save_image", "images", timeout)["content"]

    def upscale(self, image_path: str, timeout: int = 120) -> bytes:
        return self.upscale_bytes(Path(image_path).read_bytes(), timeout)

    def upscale_bytes(self, image_bytes: bytes, timeout: int = 120) -> bytes:
        uploaded_filename = self.upload_image_bytes(image_bytes, "upscale_src.png")
        raw = json.dumps(self.upscale_template)
        raw = raw.replace('"__IMAGE_FILENAME__"', json.dumps(uploaded_filename))
        workflow = json.loads(raw)
        return submit_and_wait(self.base_url, workflow, "save_image", "images", timeout)["content"]

    def upload_image_bytes(self, image_bytes: bytes, filename: str) -> str:
        return upload_unique(self.base_url, image_bytes, filename)
