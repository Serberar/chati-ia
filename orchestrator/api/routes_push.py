"""Avisos push: claves y suscripciones del navegador, y la vigilancia que avisa cuando una tarea termina o se atasca."""
import time

import requests
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from accounts import push, task_owners
from api import access
from coding import agent_watch, opencode_client
from infra.core import CONFIG, log
from models import llm_status

router = APIRouter()


PUSH_POLL_SECONDS = 10


def _tick(state: dict) -> None:
    base = CONFIG["opencode"]["base_url"]
    try:
        requests.get(f"{base}/session/status", auth=opencode_client.AUTH, timeout=3).raise_for_status()
    except requests.RequestException:
        return
    busy = set(opencode_client.busy_session_ids(base))
    waiting = opencode_client.waiting_sessions(base)

    def send(sid: str, title: str, body: str) -> None:
        owner = task_owners.owner(sid)
        if owner and push.has_devices(owner):
            try:
                what = opencode_client.task_summary(base, sid)
            except requests.RequestException:
                what = ""
            push.notify(owner, title, body.format(tarea=what or "Tarea del agente"), tag=f"chati-{sid}")

    for sid, reason in waiting.items():
        if sid not in state["asked"]:
            state["asked"].add(sid)
            send(sid, "✋ Chati necesita tu respuesta",
                 ("Te pide permiso" if reason == "permission" else "Te hace una pregunta") + ": {tarea}")
    state["asked"] -= busy
    state["done"] |= state["busy"] - busy - set(waiting)
    now = time.time()
    for sid in busy:
        try:
            count = len(opencode_client.get_task_view(base, sid)["steps"])
        except Exception:
            continue
        seen = state["progress"].get(sid)
        if not seen or seen[0] != count:
            state["progress"][sid] = (count, now)
            agent_watch.stalled.pop(sid, None)
            continue
        quiet_since = max(seen[1], llm_status.last_sign_of_life())
        looping = llm_status.retries() >= agent_watch.STALL_RETRIES
        if now - quiet_since < agent_watch.STALL_SECONDS and not looping:
            agent_watch.stalled.pop(sid, None)
        elif sid not in agent_watch.stalled:
            agent_watch.stalled[sid] = seen[1] if looping else quiet_since
            minutes = int(now - agent_watch.stalled[sid]) // 60
            why = "el modelo no llega a contestar y se reintenta una y otra vez" if looping else "sin avanzar"
            log.warning("Tarea %s atascada: %d min, %s", sid, minutes, why)
            send(sid, "⚠ El agente parece atascado",
                 f"Lleva {minutes} min {why}: {{tarea}}. Abre Chati y pulsa Reintentar.")
    for sid in set(state["progress"]) - busy:
        state["progress"].pop(sid, None)
        agent_watch.stalled.pop(sid, None)
    for sid in list(state["done"]):
        if sid in busy or sid in waiting:
            state["done"].discard(sid)
        elif sid not in agent_watch.code_watch_running:
            state["done"].discard(sid)
            result = (agent_watch.code_watch.get(sid) or {}).get("estado", "")
            title = "⚠ Revisa la tarea" if result.startswith("✗") else "✓ Tarea terminada"
            send(sid, title, "{tarea}" + (f" · {result}" if result else ""))
    state["busy"] = busy


def watch() -> None:
    state = {"busy": set(), "asked": set(), "done": set(), "progress": {}}
    while True:
        time.sleep(PUSH_POLL_SECONDS)
        try:
            _tick(state)
        except Exception as exc:
            log.warning("Vigilante de avisos: %s", exc)


class PushSubscription(BaseModel):
    subscription: dict
    device: str = ""


@router.get("/push/key")
def push_key(request: Request):
    response = JSONResponse({"key": push.public_key()})
    if request.headers.get("origin") == access.LAUNCHER_ORIGIN:
        response.headers["Access-Control-Allow-Origin"] = access.LAUNCHER_ORIGIN
    return response


@router.post("/push/subscribe")
def push_subscribe(request: Request, req: PushSubscription):
    session = request.state.session
    try:
        push.subscribe(session["user_id"], req.subscription, req.device)
    except ValueError as exc:
        return JSONResponse({"detail": str(exc)}, status_code=400)
    log.info("Avisos al movil activados en %s", req.device or "un dispositivo")
    return {"ok": True}


@router.post("/push/unsubscribe")
def push_unsubscribe(request: Request, req: PushSubscription):
    session = request.state.session
    push.unsubscribe(session["user_id"], str(req.subscription.get("endpoint", "")))
    return {"ok": True}


class PushMessage(BaseModel):
    title: str = Field(max_length=80)
    body: str = Field(max_length=300)


@router.post("/push/aviso")
def push_message(request: Request, req: PushMessage):
    session = request.state.session
    push.notify(session["user_id"], req.title, req.body, tag="chati-aviso")
    return {"ok": True, "dispositivos": push.has_devices(session["user_id"])}


@router.post("/push/test")
def push_test(request: Request):
    session = request.state.session
    if not push.has_devices(session["user_id"]):
        return JSONResponse({"detail": "No hay ningun dispositivo con los avisos activados."}, status_code=400)
    push.notify(session["user_id"], "🔔 Avisos de Chati", "Así te avisaré cuando el agente termine o te necesite.",
                tag="chati-prueba")
    return {"ok": True}
