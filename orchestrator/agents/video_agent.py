import json
import os
import tempfile
import time
from pathlib import Path

from agents import wan_workflow
from agents.comfyui_client import submit_and_wait, upload_unique
from agents.image_agent import NoModelInstalledError
from media import content_guard, video_timing
from models import model_registry

WORKFLOW_PATH = Path(__file__).parent.parent / "workflows" / "ltxv_video.json"
IMG2VIDEO_WORKFLOW_PATH = Path(__file__).parent.parent / "workflows" / "ltxv_img2video.json"


DEFAULT_SECONDS = 4
MAX_FRAMES = 257


def frames_for(seconds: float, fps: int = 24) -> int:
    blocks = max(1, -(-round(seconds * fps) // 8))
    return min(8 * blocks + 1, MAX_FRAMES)


def timeout_for(frames: int) -> int:
    return 420 + 12 * frames


def new_seed() -> int:
    return int(time.time() * 1000) % (2**32)


class VideoAgent:
    on_start = None

    def __init__(self, base_url: str):
        self.base_url = base_url.rstrip("/")
        self.template = json.loads(WORKFLOW_PATH.read_text(encoding="utf-8"))
        self.img2video_template = json.loads(IMG2VIDEO_WORKFLOW_PATH.read_text(encoding="utf-8"))

    def _entry(self, model_id: str | None) -> model_registry.ModelEntry:
        entry = model_registry.get_video_model(model_id)
        if entry is None:
            if model_id:
                raise NoModelInstalledError(f"El modelo de video '{model_id}' ya no esta instalado.")
            raise NoModelInstalledError(
                "No hay ningun modelo de video instalado. Añade uno en "
                f"{model_registry.VID_DIR} (ver Opciones > Modelos > Video)."
            )
        return entry

    def _checkpoint_path(self, model_id: str | None = None) -> str:
        return self._entry(model_id).comfy_path

    def max_seconds(self, model_id: str | None = None, fps: int = 24) -> float:
        entry = model_registry.get_video_model(model_id)
        frames = wan_workflow.MAX_FRAMES if entry and entry.architecture == "wan" else MAX_FRAMES
        return (frames - 1) / fps

    def upload_image(self, image_path: str) -> str:
        return upload_unique(self.base_url, Path(image_path).read_bytes(), Path(image_path).name)

    def generate(self, prompt: str, width: int = 768, height: int = 512, length: int | None = None,
                 fps: int = 24, steps: int = 8, cfg: float = 1.5, timeout: int | None = None,
                 model_id: str | None = None, seconds: float = DEFAULT_SECONDS, seed: int | None = None) -> bytes:
        content_guard.check(prompt)
        seed = new_seed() if seed is None else seed
        if length is None and seconds > self.max_seconds(model_id, fps) + 0.01:
            return self._chained(prompt, None, width, height, fps, model_id, seconds, seed)
        entry = self._entry(model_id)
        if entry.architecture == "wan":
            frames = length or wan_workflow.frames_for(seconds, fps)
            workflow = wan_workflow.build(prompt, entry.comfy_path, width, height, frames, fps, seed,
                                          steps=steps if steps < 8 else wan_workflow.STEPS)
            return self._run(workflow, model_id, frames, width, height, timeout or timeout_for(frames) * 3,
                             measure=steps >= 8)
        length = length or frames_for(seconds, fps)
        timeout = timeout or timeout_for(length)
        raw = json.dumps(self.template)
        raw = raw.replace('"__CHECKPOINT_PATH__"', json.dumps(entry.comfy_path))
        raw = raw.replace('"__PROMPT__"', json.dumps(prompt))
        raw = raw.replace('"__WIDTH__"', str(width))
        raw = raw.replace('"__HEIGHT__"', str(height))
        raw = raw.replace('"__LENGTH__"', str(length))
        raw = raw.replace('"__FPS__"', str(fps))
        raw = raw.replace('"__STEPS__"', str(steps))
        raw = raw.replace('"__CFG__"', str(cfg))
        raw = raw.replace('"__SEED__"', str(seed))
        return self._run(json.loads(raw), model_id, length, width, height, timeout, measure=steps >= 8)

    def _run(self, workflow: dict, model_id: str | None, frames: int, width: int, height: int, timeout: int,
             measure: bool = True) -> bytes:
        if measure and self.on_start:
            self.on_start(video_timing.say(video_timing.estimate(model_id, frames, width, height)))
        started = time.time()
        content = submit_and_wait(self.base_url, workflow, "save_video", ["images", "videos"], timeout)["content"]
        if measure:
            video_timing.record(model_id, frames, width, height, time.time() - started)
        return content

    def generate_from_image(self, prompt: str, start_image_path: str, width: int = 768, height: int = 512,
                             length: int | None = None, fps: int = 24, steps: int = 8, cfg: float = 1.5,
                             timeout: int | None = None, model_id: str | None = None,
                             seconds: float = DEFAULT_SECONDS, seed: int | None = None) -> bytes:
        content_guard.check(prompt)
        seed = new_seed() if seed is None else seed
        if length is None and seconds > self.max_seconds(model_id, fps) + 0.01:
            return self._chained(prompt, start_image_path, width, height, fps, model_id, seconds, seed)
        entry = self._entry(model_id)
        uploaded_filename = self.upload_image(start_image_path)
        if entry.architecture == "wan":
            frames = length or wan_workflow.frames_for(seconds, fps)
            workflow = wan_workflow.build(prompt, entry.comfy_path, width, height, frames, fps, seed,
                                          start_image=uploaded_filename,
                                          steps=steps if steps < 8 else wan_workflow.STEPS)
            return self._run(workflow, model_id, frames, width, height, timeout or timeout_for(frames) * 3,
                             measure=steps >= 8)
        length = length or frames_for(seconds, fps)
        timeout = timeout or timeout_for(length)

        raw = json.dumps(self.img2video_template)
        raw = raw.replace('"__CHECKPOINT_PATH__"', json.dumps(entry.comfy_path))
        raw = raw.replace('"__PROMPT__"', json.dumps(prompt))
        raw = raw.replace('"__WIDTH__"', str(width))
        raw = raw.replace('"__HEIGHT__"', str(height))
        raw = raw.replace('"__LENGTH__"', str(length))
        raw = raw.replace('"__FPS__"', str(fps))
        raw = raw.replace('"__STEPS__"', str(steps))
        raw = raw.replace('"__CFG__"', str(cfg))
        raw = raw.replace('"__SEED__"', str(seed))
        raw = raw.replace('"__IMAGE_FILENAME__"', json.dumps(uploaded_filename))
        return self._run(json.loads(raw), model_id, length, width, height, timeout, measure=steps >= 8)

    def _chained(self, prompt: str, start_image_path: str | None, width: int, height: int, fps: int,
                 model_id: str | None, seconds: float, seed: int) -> bytes:
        from media import film
        parts = int(-(-seconds // self.max_seconds(model_id, fps)))
        each = seconds / parts
        clips: list[bytes] = []
        for i in range(parts):
            if i == 0 and start_image_path is None:
                clips.append(self.generate(prompt, width, height, fps=fps, model_id=model_id, seconds=each,
                                           seed=seed))
                continue
            if i == 0:
                frame_path = start_image_path
            else:
                with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp:
                    tmp.write(film.last_frame(clips[-1]))
                frame_path = tmp.name
            try:
                clips.append(self.generate_from_image(prompt, frame_path, width, height, fps=fps, model_id=model_id,
                                                      seconds=each, seed=seed))
            finally:
                if i > 0:
                    os.unlink(frame_path)
        return film.concat(clips, fps=fps, fade=0)
