"""Memoria de la GPU: que modelos de Ollama quedan cargados y cuando se libera ComfyUI."""
import threading

from agents import comfyui_client
from chat.rag import EMBED_MODEL
from coding import opencode_client
from infra.core import CONFIG, ollama
from models import llm_proxy

last_comfy_warmup: tuple[str, str | None] | None = None


def free_comfyui() -> None:
    global last_comfy_warmup
    running, _ = comfyui_client.user_queue(CONFIG["comfyui"]["base_url"])
    if running:
        return
    comfyui_client.free_memory(CONFIG["comfyui"]["base_url"])
    last_comfy_warmup = None


LIGHT_MODEL = CONFIG["router"]["model"]
_active_heavy_model: str | None = None
_heavy_model_lock = threading.Lock()


def ensure_active_model(model: str) -> None:
    global _active_heavy_model
    new_heavy = model if model != LIGHT_MODEL else None
    with _heavy_model_lock:
        old_heavy = _active_heavy_model
        if old_heavy and old_heavy != new_heavy:
            ollama.unload(old_heavy)
        _active_heavy_model = new_heavy


def agent_models() -> set[str]:
    oc = CONFIG["opencode"]
    potente = oc["model_potente"]
    return {oc["model"], potente, potente.removesuffix(llm_proxy.MIXED_SUFFIX) + "-cpu"}


def free_memory_for_generation() -> None:
    global _active_heavy_model
    keep = set()
    if opencode_client.busy_session_ids(CONFIG["opencode"]["base_url"]):
        keep |= {m for m in agent_models() if not m.endswith(llm_proxy.MIXED_SUFFIX)}
    with _heavy_model_lock:
        for model in ollama.running_models():
            if model not in keep:
                ollama.unload(model)
        _active_heavy_model = None


def _agent_model(agent: str | None, model: str | None = None) -> str:
    if model:
        return model
    oc = CONFIG["opencode"]
    heavy = {oc["agent_potente"], oc.get("agent_code"), oc.get("agent_code_plan")}
    return oc["model_potente"] if agent in heavy else oc["model"]


def free_memory_for_agent(agent: str | None, model: str | None = None, wait: bool = False) -> None:
    model = _agent_model(agent, model)
    potente = model == CONFIG["opencode"]["model_potente"]

    def work():
        cpu_only = potente and not model.endswith(llm_proxy.MIXED_SUFFIX)
        keep = {model, EMBED_MODEL} | ({LIGHT_MODEL} if cpu_only else set())
        keep_only_ollama(keep, heavy=model)
        comfyui_client.free_memory(CONFIG["comfyui"]["base_url"])
        share = ollama.gpu_share(model)
        if not potente and share is not None and share < 0.5 \
                and not opencode_client.busy_session_ids(CONFIG["opencode"]["base_url"]):
            ollama.unload(model)

    if wait:
        work()
    else:
        threading.Thread(target=work, daemon=True).start()


def _same_model(loaded: str, wanted: str) -> bool:
    return loaded == wanted or loaded == f"{wanted}:latest"


def keep_only_ollama(keep: set[str], heavy: str | None = None) -> None:
    global _active_heavy_model
    keep = set(keep)
    if opencode_client.busy_session_ids(CONFIG["opencode"]["base_url"]):
        keep |= agent_models()
    with _heavy_model_lock:
        for model in ollama.running_models():
            if not any(_same_model(model, k) for k in keep):
                ollama.unload(model)
        _active_heavy_model = heavy
