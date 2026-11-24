import json
import logging
import threading
import time
import uuid
from collections.abc import Callable
from contextvars import ContextVar
from pathlib import Path

import requests

from infra import paths


class GenerationCancelled(Exception):
    pass


before_submit: Callable[[], None] | None = None

current_owner: ContextVar[str | None] = ContextVar("comfy_owner", default=None)
_owners: dict[str, str] = {}
current_conversation: ContextVar[str | None] = ContextVar("comfy_conversation", default=None)
_conversations: dict[str, str] = {}
_last_conversation: dict[str, str] = {}


def note_conversation(owner: str | None, conversation: str) -> None:
    current_conversation.set(conversation)
    if owner:
        with _owners_lock:
            _last_conversation[owner] = conversation
_owners_lock = threading.Lock()


_active = 0
_active_lock = threading.Lock()


def generation_running() -> bool:
    with _active_lock:
        return _active > 0


CLIENT_ID = f"chati-{uuid.uuid4().hex}"
_progress: dict[str, dict] = {}
_listener_started = threading.Event()


def _describe_node(class_type: str) -> str:
    c = class_type.lower()
    for words, text in ((("loader", "load"), "Cargando el modelo"), (("sampler",), "Generando"),
                        (("decode",), "Pasando el resultado a imagen"), (("upscale",), "Ampliando"),
                        (("save", "videocombine", "preview"), "Guardando"),
                        (("encode", "cliptext"), "Preparando la descripción")):
        if any(w in c for w in words):
            return text
    return "Preparando la generación"


def _on_comfy_event(msg: dict) -> None:
    kind, data = msg.get("type"), msg.get("data") or {}
    with _owners_lock:
        p = _progress.get(data.get("prompt_id"))
        if p is None:
            return
        if kind == "executing" and data.get("node"):
            p.update(node=str(data["node"]), value=0, max=0, since=time.time())
        elif kind == "progress":
            if str(data.get("node")) != p["node"]:
                p.update(node=str(data.get("node")), since=time.time())
            p.update(value=data.get("value", 0), max=data.get("max", 0), last_step=time.time())


def _listen(base_url: str) -> None:
    from websockets.sync.client import connect
    url = base_url.replace("http", "ws", 1) + f"/ws?clientId={CLIENT_ID}"
    while True:
        try:
            with connect(url, open_timeout=5, max_size=None) as ws:
                for frame in ws:
                    if isinstance(frame, str):
                        try:
                            _on_comfy_event(json.loads(frame))
                        except ValueError:
                            pass
        except Exception:
            time.sleep(3)


def _ensure_listener(base_url: str) -> None:
    if not _listener_started.is_set():
        _listener_started.set()
        threading.Thread(target=_listen, args=(base_url,), daemon=True).start()


def conversation_progress(conversation: str) -> dict | None:
    with _owners_lock:
        ids = [pid for pid, conv in _conversations.items() if conv == conversation]
    return next((p for p in map(job_progress, ids) if p), None)


def job_progress(prompt_id: str) -> dict | None:
    with _owners_lock:
        p = _progress.get(prompt_id)
        if not p or not p["node"]:
            return None
        text = _describe_node(p["nodes"].get(p["node"], ""))
        if p["max"]:
            text += f": paso {p['value']} de {p['max']}"
        elif text == "Generando":
            text += ": pasando el modelo a la tarjeta gráfica"
        return {"texto": text, "desde": p["since"], "ultimo_paso": p.get("last_step")}


_queue_seen = {"at": 0.0, "busy": False}


def gpu_busy(base_url: str) -> bool:
    if generation_running():
        return True
    now = time.time()
    if now - _queue_seen["at"] > 2:
        try:
            queue = requests.get(f"{base_url}/queue", timeout=0.5).json()
            busy = bool(queue.get("queue_running") or queue.get("queue_pending"))
            if not busy:
                device = requests.get(f"{base_url}/system_stats", timeout=0.5).json()["devices"][0]
                busy = device["torch_vram_total"] > FREED_VRAM_BYTES
        except (requests.RequestException, ValueError, AttributeError, KeyError, IndexError):
            busy = False
        _queue_seen.update(at=now, busy=busy)
    return _queue_seen["busy"]


def owner_of(prompt_id: str) -> str | None:
    with _owners_lock:
        return _owners.get(prompt_id)


def stop_owned(base_url: str, owner: str) -> int:
    mine = [j for j in user_jobs(base_url) if owner_of(j["id"]) == owner]
    for job in mine:
        stop_job(base_url, job["id"])
    return len(mine)

def _comfy_dir() -> Path:
    return paths.DATA_ROOT / "ComfyUI"


COMFY_DIR: Callable[[], Path] | Path = _comfy_dir

FREED_VRAM_BYTES = 512 * 1024 * 1024


def _is_still_queued(base_url: str, prompt_id: str) -> bool:
    try:
        queue = requests.get(f"{base_url}/queue", timeout=10).json()
    except (requests.RequestException, ValueError):
        return True
    if not isinstance(queue, dict):
        return True
    items = queue.get("queue_running", []) + queue.get("queue_pending", [])
    return any(item[1] == prompt_id for item in items)


def _in_history(base_url: str, prompt_id: str) -> bool:
    try:
        return prompt_id in requests.get(f"{base_url}/history/{prompt_id}", timeout=10).json()
    except (requests.RequestException, ValueError):
        return True


def submit_and_wait(base_url: str, workflow: dict, save_node: str, output_keys: list[str] | str,
                     timeout: int) -> dict:
    if isinstance(output_keys, str):
        output_keys = [output_keys]
    global _active
    if before_submit is not None:
        before_submit()
    with _active_lock:
        _active += 1
    try:
        return _submit_and_wait(base_url, workflow, save_node, output_keys, timeout)
    finally:
        with _active_lock:
            _active -= 1


def _submit_and_wait(base_url: str, workflow: dict, save_node: str, output_keys: list[str],
                     timeout: int) -> dict:

    _ensure_listener(base_url)
    resp = requests.post(
        f"{base_url}/prompt",
        json={"prompt": workflow, "client_id": CLIENT_ID},
        timeout=30,
    )
    resp.raise_for_status()
    prompt_id = resp.json()["prompt_id"]
    owner, conversation = current_owner.get(), current_conversation.get()
    with _owners_lock:
        _progress[prompt_id] = {"nodes": {k: v.get("class_type", "") for k, v in workflow.items()
                                          if isinstance(v, dict)},
                                "node": None, "value": 0, "max": 0, "since": time.time()}
        conversation = conversation or (_last_conversation.get(owner) if owner else None)
        if owner:
            _owners[prompt_id] = owner
        if conversation:
            _conversations[prompt_id] = conversation

    deadline = time.time() + timeout
    grace_deadline = time.time() + 5

    while time.time() < deadline:
        try:
            hist = requests.get(f"{base_url}/history/{prompt_id}", timeout=10).json()
        except (requests.RequestException, ValueError):
            time.sleep(2)
            continue
        if prompt_id in hist:
            status = hist[prompt_id].get("status", {})
            if status.get("status_str") == "error":
                forget(base_url, prompt_id, workflow)
                messages = status.get("messages", [])
                was_interrupted = any(m[0] == "execution_interrupted" for m in messages)
                if was_interrupted:
                    raise GenerationCancelled(f"Generacion cancelada (prompt_id={prompt_id})")
                raise RuntimeError(f"ComfyUI fallo: {status}")
            outputs = hist[prompt_id]["outputs"]
            node_output = outputs.get(save_node, {})
            items = []
            for key in output_keys:
                items = node_output.get(key, [])
                if items:
                    break
            if not items:
                raise RuntimeError(f"ComfyUI no devolvio resultado en '{save_node}.{output_keys}': {outputs}")
            info = items[0]
            file_resp = requests.get(
                f"{base_url}/view",
                params={"filename": info["filename"], "subfolder": info.get("subfolder", ""),
                        "type": info.get("type", "output")},
                timeout=60,
            )
            file_resp.raise_for_status()
            forget(base_url, prompt_id, workflow, info)
            return {"content": file_resp.content, "prompt_id": prompt_id}

        if time.time() > grace_deadline and not _is_still_queued(base_url, prompt_id):
            if _in_history(base_url, prompt_id):
                continue
            forget(base_url, prompt_id, workflow)
            raise GenerationCancelled(f"Generacion cancelada (prompt_id={prompt_id})")

        time.sleep(1)

    try:
        stop_job(base_url, prompt_id)
    except requests.RequestException:
        pass
    forget(base_url, prompt_id, workflow)
    raise TimeoutError(f"Generacion no termino en {timeout}s (prompt_id={prompt_id})")


def upload_unique(base_url: str, image_bytes: bytes, filename: str) -> str:
    suffix = Path(filename).suffix.lower() or ".png"
    unique = f"chati_{uuid.uuid4().hex}{suffix if suffix in ('.png', '.jpg', '.jpeg', '.webp') else '.png'}"
    resp = requests.post(f"{base_url}/upload/image", files={"image": (unique, image_bytes)}, timeout=30)
    resp.raise_for_status()
    return resp.json()["name"]


def _try_unlink(path: Path) -> bool:
    try:
        path.unlink(missing_ok=True)
        return True
    except OSError:
        return False


def _unlink_later(paths: list[Path], attempts: int = 20, delay: float = 1.0) -> None:
    for _ in range(attempts):
        time.sleep(delay)
        paths = [p for p in paths if not _try_unlink(p)]
        if not paths:
            return
    for p in paths:
        logging.getLogger("chati").warning("No se pudo borrar la copia de ComfyUI %s", p.name)


def forget(base_url: str, prompt_id: str, workflow: dict, output_info: dict | None = None) -> None:
    with _owners_lock:
        _owners.pop(prompt_id, None)
        _conversations.pop(prompt_id, None)
        _progress.pop(prompt_id, None)
    root = COMFY_DIR() if callable(COMFY_DIR) else COMFY_DIR
    targets = []
    if output_info and output_info.get("filename"):
        kind = output_info.get("type", "output")
        if kind in ("output", "temp"):
            targets.append(root / kind / output_info.get("subfolder", "") / output_info["filename"])
    for node in (workflow or {}).values():
        if not isinstance(node, dict) or not str(node.get("class_type", "")).startswith("LoadImage"):
            continue
        name = (node.get("inputs") or {}).get("image")
        if isinstance(name, str) and name and "/" not in name and "\\" not in name and ".." not in name:
            targets.append(root / "input" / name)
    pending = [p for p in targets if not _try_unlink(p)]
    if pending:
        threading.Thread(target=_unlink_later, args=(pending,), daemon=True).start()
    try:
        requests.post(f"{base_url}/history", json={"delete": [prompt_id]}, timeout=5)
    except requests.RequestException:
        pass


def free_memory(base_url: str) -> None:
    try:
        requests.post(f"{base_url}/free", json={"unload_models": True, "free_memory": True}, timeout=10)
        deadline = time.time() + 10
        while time.time() < deadline:
            device = requests.get(f"{base_url}/system_stats", timeout=5).json()["devices"][0]
            if device["torch_vram_total"] <= FREED_VRAM_BYTES:
                return
            time.sleep(0.5)
    except (requests.RequestException, ValueError, KeyError, IndexError):
        pass


def interrupt(base_url: str) -> None:
    requests.post(f"{base_url}/interrupt", timeout=10)


WARMUP_PROMPT = "warm up"


def user_jobs(base_url: str) -> list[dict]:
    try:
        queue = requests.get(f"{base_url}/queue", timeout=5).json()
    except (requests.RequestException, ValueError):
        return []

    def is_user_job(item) -> bool:
        return f'"{WARMUP_PROMPT}"' not in json.dumps(item[2] if len(item) > 2 else {})

    def job(item, state: str) -> dict:
        with _owners_lock:
            session_id = _conversations.get(item[1])
        return {"id": item[1], "state": state, "session_id": session_id,
                "progreso": job_progress(item[1]) if state == "running" else None}

    return ([job(item, "running") for item in queue.get("queue_running", []) if is_user_job(item)]
            + [job(item, "queued") for item in queue.get("queue_pending", []) if is_user_job(item)])


def user_queue(base_url: str) -> tuple[int, int]:
    jobs = user_jobs(base_url)
    return (sum(j["state"] == "running" for j in jobs), sum(j["state"] == "queued" for j in jobs))


def stop_job(base_url: str, prompt_id: str) -> None:
    if any(j["id"] == prompt_id and j["state"] == "running" for j in user_jobs(base_url)):
        requests.post(f"{base_url}/interrupt", timeout=10)
    else:
        requests.post(f"{base_url}/queue", json={"delete": [prompt_id]}, timeout=10)


def stop_everything(base_url: str) -> None:
    requests.post(f"{base_url}/queue", json={"clear": True}, timeout=10)
    requests.post(f"{base_url}/interrupt", timeout=10)
