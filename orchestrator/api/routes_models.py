"""Rutas de modelos y ajustes: listar, borrar y preparar modelos y actualizaciones."""
import re
import subprocess
import threading

import requests
from fastapi import APIRouter, Form, Request
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel

from agents import comfyui_client
from api import access, security
from chat.rag import EMBED_MODEL
from infra import app_update, autostart
from infra.core import CONFIG, image_agent, log, ollama, text_agent, video_agent, vision_agent
from media import media_store
from models import finetune_export, gpu_memory, model_choice, model_registry, model_updates

router = APIRouter()


@router.get("/models/updates")
def get_model_updates(force: bool = False):
    return {"updates": model_updates.check_updates(force=force)}


@router.post("/models/update", dependencies=[access.admin_only("Solo un administrador puede actualizar modelos.")])
def trigger_model_update(model: str = Form(...), request: Request = None):
    known = {r["model"] for r in model_updates.check_updates()}
    if model not in known:
        return JSONResponse({"detail": f"Modelo desconocido o no instalado: {model}"}, status_code=400)
    subprocess.Popen(["ollama", "pull", model], creationflags=subprocess.CREATE_NO_WINDOW)
    return {"ok": True, "message": f"Descarga de {model} iniciada en segundo plano."}


@router.get("/app/update", dependencies=[access.admin_only("Solo un administrador puede actualizar Chati.")])
def get_app_update(request: Request, force: bool = False):
    return app_update.check(force=force)


@router.post("/app/update", dependencies=[access.admin_only("Solo un administrador puede actualizar Chati.")])
def install_app_update(request: Request):
    if not security.is_local_host(request.headers.get("host", "")):
        return JSONResponse({"detail": "Actualiza desde el propio ordenador: Windows pide permiso allí."},
                            status_code=403)
    try:
        version = app_update.install()
    except app_update.UpdateError as exc:
        return JSONResponse({"detail": str(exc)}, status_code=502)
    log.info("Actualizacion de Chati a la %s lanzada", version)
    return {"ok": True, "version": version}


class GithubTokenRequest(BaseModel):
    token: str


@router.post("/app/github_token", dependencies=[access.admin_only("Solo un administrador puede actualizar Chati.")])
def save_github_token(request: Request, req: GithubTokenRequest):
    if not re.fullmatch(r"(github_pat_|ghp_)[A-Za-z0-9_]{20,255}", req.token.strip()):
        return JSONResponse({"detail": "Eso no parece un token de GitHub (empieza por github_pat_ o ghp_)."},
                            status_code=400)
    app_update.set_token(req.token)
    return {"ok": True}


def _local_admin_error(request: Request) -> JSONResponse | None:
    if request.state.session["role"] != "admin":
        return JSONResponse({"detail": "Solo un administrador puede cambiar esto."}, status_code=403)
    if not security.is_local_host(request.headers.get("host", "")):
        return JSONResponse({"detail": "Esto se cambia desde el propio ordenador."}, status_code=403)
    return None


@router.get("/app/autostart")
def get_autostart(request: Request):
    return _local_admin_error(request) or {"enabled": autostart.enabled()}


class AutostartRequest(BaseModel):
    enabled: bool


@router.post("/app/autostart")
def set_autostart(req: AutostartRequest, request: Request):
    error = _local_admin_error(request)
    if error:
        return error
    try:
        autostart.set_enabled(req.enabled)
    except (OSError, subprocess.SubprocessError) as exc:
        return JSONResponse({"detail": f"No se pudo cambiar: {exc}"}, status_code=500)
    return {"enabled": autostart.enabled()}


@router.delete("/models/text/{model}", dependencies=[access.admin_only("Solo un administrador puede borrar modelos.")])
def delete_text_model(model: str, request: Request):
    known = {r["model"] for r in model_updates.check_updates()}
    if model not in known:
        return JSONResponse({"detail": f"Modelo desconocido o no instalado: {model}"}, status_code=400)
    if model in get_model_roles():
        return JSONResponse(
            {"detail": f"'{model}' esta en uso ahora mismo - no se puede borrar."}, status_code=400
        )
    resp = requests.delete(f"{CONFIG['ollama']['base_url']}/api/delete", json={"model": model}, timeout=30)
    if not resp.ok:
        return JSONResponse({"detail": f"Ollama no pudo borrar el modelo: {resp.text}"}, status_code=502)
    return {"ok": True, "message": f"'{model}' borrado."}


@router.get("/models/image")
def get_image_models():
    models = model_registry.list_image_models()
    return {
        "models": [
            {"id": m.id, "architecture": m.architecture, "architecture_label": m.architecture_label, "label": m.label}
            for m in models
        ],
        "architectures": model_registry.list_image_architectures(),
        "base_folder": str(model_registry.IMG_DIR),
    }


@router.get("/models/video")
def get_video_models():
    models = model_registry.list_video_models()
    return {
        "models": [
            {"id": m.id, "architecture": m.architecture, "architecture_label": m.architecture_label, "label": m.label}
            for m in models
        ],
        "architectures": model_registry.list_video_architectures(),
        "base_folder": str(model_registry.VID_DIR),
    }


@router.delete("/models/image/{model_id}", dependencies=[access.admin_only("Solo un administrador puede borrar modelos.")])
def delete_image_model(model_id: str, request: Request):
    path = model_registry.image_model_path(model_id)
    if path is None or not path.exists():
        return JSONResponse({"detail": f"Modelo desconocido o no instalado: {model_id}"}, status_code=400)
    try:
        path.unlink()
    except OSError as exc:
        return JSONResponse({"detail": f"No se pudo borrar el archivo: {exc}"}, status_code=502)
    return {"ok": True, "message": f"'{model_id}' borrado."}


@router.delete("/models/video/{model_id}", dependencies=[access.admin_only("Solo un administrador puede borrar modelos.")])
def delete_video_model(model_id: str, request: Request):
    path = model_registry.video_model_path(model_id)
    if path is None or not path.exists():
        return JSONResponse({"detail": f"Modelo desconocido o no instalado: {model_id}"}, status_code=400)
    try:
        path.unlink()
    except OSError as exc:
        return JSONResponse({"detail": f"No se pudo borrar el archivo: {exc}"}, status_code=502)
    return {"ok": True, "message": f"'{model_id}' borrado."}
PREPARE_MODES = {"chat", "texto", "image", "video", "agente", "codigo", "voice"}
_prepare_state = {"mode": None, "state": "idle", "detail": None, "label": None, "ticket": 0}
_prepare_lock = threading.Lock()


class PrepareRequest(BaseModel):
    mode: str
    potente: bool = False
    model_profile: str | None = None
    image_model: str | None = None
    video_model: str | None = None


def _chat_model_for(profile: str | None) -> str:
    default = CONFIG["agents"]["text"].get("default_profile")
    return model_choice.profile_model(profile or default) or text_agent.model


def _prepare_work(req: PrepareRequest) -> None:
    mode = req.mode
    if mode == "chat":
        gpu_memory.free_comfyui()
        target = _chat_model_for(req.model_profile)
        gpu_memory.keep_only_ollama({gpu_memory.LIGHT_MODEL, target, EMBED_MODEL},
                          heavy=target if target != gpu_memory.LIGHT_MODEL else None)
        ollama.preload(gpu_memory.LIGHT_MODEL)
        if target != gpu_memory.LIGHT_MODEL:
            ollama.preload(target)
    elif mode in ("texto", "voice"):
        gpu_memory.free_comfyui()
        target = _chat_model_for(req.model_profile)
        gpu_memory.keep_only_ollama({target, gpu_memory.LIGHT_MODEL, EMBED_MODEL},
                          heavy=target if target != gpu_memory.LIGHT_MODEL else None)
        ollama.preload(target)
    elif mode in ("image", "video"):
        model_id = req.image_model if mode == "image" else req.video_model
        if gpu_memory.last_comfy_warmup not in (None, (mode, model_id)):
            gpu_memory.free_comfyui()
        if mode == "image":
            image_agent.generate(comfyui_client.WARMUP_PROMPT, width=256, height=256, model_id=model_id, timeout=600)
        else:
            video_agent.generate(comfyui_client.WARMUP_PROMPT, width=256, height=160, length=9, steps=2,
                                 model_id=model_id, timeout=600)
        gpu_memory.last_comfy_warmup = (mode, model_id)
    elif mode in ("agente", "codigo"):
        gpu_memory.free_comfyui()
        model = CONFIG["opencode"]["model_potente" if req.potente else "model"]
        keep = {model, EMBED_MODEL} | ({gpu_memory.LIGHT_MODEL} if req.potente else set())
        gpu_memory.keep_only_ollama(keep, heavy=model)
        ollama.preload(model)


def _prepare_label(req: PrepareRequest) -> str:
    if req.mode in ("chat", "texto", "voice"):
        return f"el modelo del chat ({_chat_model_for(req.model_profile)})"
    if req.mode == "image":
        entry = model_registry.get_image_model(req.image_model)
        return f"el generador de imagenes ({entry.label})" if entry else "el generador de imagenes"
    if req.mode == "video":
        entry = model_registry.get_video_model(req.video_model)
        return f"el generador de video ({entry.label})" if entry else "el generador de video"
    if req.potente:
        return f"el modelo potente del agente ({CONFIG['opencode']['model_potente']}, ~26 GB)"
    return f"el modelo del agente ({CONFIG['opencode']['model']})"


def _run_prepare(req: PrepareRequest, ticket: int) -> None:
    try:
        _prepare_work(req)
        state, detail = "ready", None
    except Exception as exc:
        log.warning("No se pudo preparar el modo %s: %s", req.mode, exc)
        state, detail = "error", str(exc)
    with _prepare_lock:
        stale = _prepare_state["ticket"] != ticket
        now_generating = _prepare_state["mode"] in ("image", "video")
        if not stale:
            _prepare_state.update(state=state, detail=detail)
    if stale and now_generating and req.mode not in ("image", "video"):
        gpu_memory.keep_only_ollama(set(), heavy=None)


@router.post("/models/prepare")
def prepare_models(req: PrepareRequest):
    if req.mode not in PREPARE_MODES:
        return JSONResponse({"detail": "Modo desconocido."}, status_code=400)
    with _prepare_lock:
        _prepare_state["ticket"] += 1
        ticket = _prepare_state["ticket"]
        _prepare_state.update(mode=req.mode, state="preparing", detail=None, label=_prepare_label(req))
    threading.Thread(target=_run_prepare, args=(req, ticket), daemon=True, name=f"preparar-{ticket}").start()
    return {"mode": req.mode, "state": "preparing"}


@router.get("/models/prepare")
def prepare_status():
    with _prepare_lock:
        return {k: v for k, v in _prepare_state.items() if k != "ticket"}


@router.get("/models/profiles")
def get_model_profiles():
    profiles = CONFIG["agents"]["text"].get("profiles", {})
    return {
        "profiles": [{"id": pid, "label": p["label"]} for pid, p in profiles.items()],
        "default": CONFIG["agents"]["text"].get("default_profile"),
    }


@router.get("/models/roles")
def get_model_roles():
    text_cfg = CONFIG["agents"]["text"]
    profiles = text_cfg.get("profiles", {})
    roles: dict[str, list[str]] = {}

    def add(model: str | None, desc: str) -> None:
        if not model:
            return
        descs = roles.setdefault(model, [])
        if desc not in descs:
            descs.append(desc)

    add(CONFIG["router"]["model"], "Router (decide que agente atiende cada mensaje)")
    add(CONFIG["verifier"]["model"], "Verificador (revisa que las respuestas no inventen datos)")
    for profile in profiles.values():
        add(profile["model"], f'Chat, perfil "{profile["label"]}"')
    add(text_cfg.get("model"), "Chat de texto (modelo por defecto sin perfil)")
    add(CONFIG["agents"]["code"]["model"], "Programacion")
    add(vision_agent.model, "Vision (comentar fotos que subes)")
    embed_model_id = EMBED_MODEL if ":" in EMBED_MODEL else f"{EMBED_MODEL}:latest"
    add(embed_model_id, "Embeddings (busqueda semantica interna: memoria y documentos)")

    return {model: " · ".join(descs) for model, descs in roles.items()}


@router.get("/models/status")
def get_models_status():
    try:
        resp = requests.get(f"{CONFIG['ollama']['base_url']}/api/ps", timeout=5)
        resp.raise_for_status()
        return resp.json()
    except requests.RequestException as exc:
        return JSONResponse({"detail": f"No se pudo consultar Ollama: {exc}"}, status_code=503)


@router.post("/finetune/export")
def export_finetune_data(request: Request):
    session = request.state.session

    out_path = media_store.new_tmp_path(".jsonl")
    try:
        count = finetune_export.export_user_conversations_chatml(
            user_id=session["user_id"], dek=session["dek"], key_generation=session["key_generation"],
            out_path=out_path,
        )
        data = out_path.read_bytes() if out_path.exists() else b""
    finally:
        out_path.unlink(missing_ok=True)
    return Response(data, media_type="application/x-ndjson", headers={
        "Content-Disposition": 'attachment; filename="chati_conversaciones.jsonl"',
        "X-Conversations-Exported": str(count)})
