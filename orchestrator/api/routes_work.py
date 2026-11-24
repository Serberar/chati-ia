"""Rutas de trabajos en curso: ver lo pendiente y parar generaciones o tareas del agente."""
import logging
import time

import requests
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from agents import comfyui_client
from api import access, routes_agent
from coding import agent_watch, opencode_client
from infra.core import CONFIG, log
from models import llm_status

_logger = logging.getLogger(__name__)

router = APIRouter()


@router.post("/cancel")
def cancel_generation(request: Request):
    n = comfyui_client.stop_owned(CONFIG["comfyui"]["base_url"], access.owner_of(request.state.session))
    log.info("Detener: %d generacion(es) paradas, pedido desde %s", n, routes_agent.where(request))
    return {"ok": True}


@router.get("/work/pending")
def pending_work(request: Request):
    base = CONFIG["opencode"]["base_url"]

    def summary(sid: str) -> str:
        try:
            return opencode_client.task_summary(base, sid)
        except requests.RequestException:
            return ""

    now_doing = llm_status.snapshot()
    agent_tasks = [{"session_id": sid, "title": summary(sid), "modelo_ahora": now_doing,
                    "atascada_min": int(time.time() - agent_watch.stalled[sid]) // 60 if sid in agent_watch.stalled else 0}
                   for sid in opencode_client.busy_session_ids(base) if routes_agent.owns_task(request, sid)]
    waiting_tasks = [{"session_id": sid, "title": summary(sid), "reason": reason}
                     for sid, reason in opencode_client.waiting_sessions(base).items()
                     if routes_agent.owns_task(request, sid)]
    generations = [g for g in comfyui_client.user_jobs(CONFIG["comfyui"]["base_url"])
                   if _may_stop_generation(request, g["id"])]
    running = sum(g["state"] == "running" for g in generations)
    queued = sum(g["state"] == "queued" for g in generations)
    return {"agent_tasks": agent_tasks, "waiting_tasks": waiting_tasks, "generations": generations,
            "generations_running": running, "generations_queued": queued,
            "any": bool(agent_tasks or running or queued)}


@router.post("/work/agent/{session_id}/stop")
def stop_agent_task(session_id: str, request: Request):
    if not routes_agent.owns_task(request, session_id):
        return routes_agent.not_your_task()
    result = routes_agent.opencode_call(opencode_client.stop_task, session_id)
    return result if isinstance(result, JSONResponse) else {"ok": True}


def _may_stop_generation(request: Request, prompt_id: str) -> bool:
    owner = comfyui_client.owner_of(prompt_id)
    session = request.state.session
    return owner == access.owner_of(session) or (owner is None and session["role"] == "admin")


@router.post("/work/generation/{prompt_id}/stop")
def stop_generation(prompt_id: str, request: Request):
    if not _may_stop_generation(request, prompt_id):
        return JSONResponse({"detail": "Esa generacion no es tuya."}, status_code=403)
    try:
        comfyui_client.stop_job(CONFIG["comfyui"]["base_url"], prompt_id)
    except requests.RequestException as exc:
        return JSONResponse({"detail": f"ComfyUI no responde: {exc}"}, status_code=502)
    log.info("Detener (tareas en segundo plano): generacion %s, pedido desde %s", prompt_id, routes_agent.where(request))
    return {"ok": True}


@router.post("/work/stop")
def stop_work(request: Request):
    base = CONFIG["opencode"]["base_url"]
    for sid in opencode_client.busy_session_ids(base):
        if not routes_agent.owns_task(request, sid):
            continue
        try:
            opencode_client.abort(base, sid)
        except requests.RequestException:
            _logger.debug("stop_work: se sigue sin ello", exc_info=True)
    try:
        n = comfyui_client.stop_owned(CONFIG["comfyui"]["base_url"], access.owner_of(request.state.session))
        log.info("Detener todo: %d generacion(es) paradas, pedido desde %s", n, routes_agent.where(request))
    except requests.RequestException:
        _logger.debug("stop_work: se sigue sin ello", exc_info=True)
    return {"ok": True}
