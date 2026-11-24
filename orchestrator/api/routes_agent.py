"""Rutas del agente y del modo codigo: tareas, permisos, preguntas, proyectos y atajos."""
import json
import re
import subprocess
import sys
import time
from pathlib import Path

import requests
from fastapi import APIRouter, File, Request, UploadFile
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel

from accounts import profile_store, task_owners
from api import access
from api.replies import MAX_DOC_BYTES, read_upload
from chat import night_queue, web_tools
from chat.router import complex_hint
from coding import (agent_attachments, agent_guard, agent_tools, agent_watch, checkpoints, code_checks, lessons,
                    opencode_client, prefetch, project_git, project_rules, routines, trajectories)
from infra import core
from infra.core import CONFIG, log, ollama, vision_agent
from models import gpu_memory, llm_status

router = APIRouter()


def where(request: Request) -> str:
    device = getattr(request.state, "device", None)
    return f"el dispositivo vinculado '{device['name']}'" if device else "el ordenador"


class AgentTaskRequest(BaseModel):
    task: str
    potente: bool = False
    confirmed: bool = False
    attachments: list[dict] = []
    project: str | None = None
    plan: bool = False
    rapido: bool = False
    autonomo: bool = False
    continuar: str | None = None
IMAGE_DESCRIBE_PROMPT = ("Describe en una sola frase, en español, que se ve en esta imagen, para poder "
                         "clasificarla o ponerle nombre. Si hay texto importante (un titulo, un total, una "
                         "fecha), incluyelo.")


@router.post("/agent/attachments")
def agent_upload_attachments(request: Request, files: list[UploadFile] = File(...)):
    try:
        folder, saved = agent_attachments.save_batch([(f.filename, read_upload(f, MAX_DOC_BYTES)) for f in files])
    except ValueError as exc:
        return JSONResponse({"detail": str(exc)}, status_code=400)
    if any(Path(i["path"]).suffix.lower() in agent_attachments.IMAGE_SUFFIXES for i in saved):
        gpu_memory.ensure_active_model(vision_agent.model)
        agent_attachments.describe_images(
            saved, lambda b64: "".join(vision_agent.respond_with_image_stream(IMAGE_DESCRIBE_PROMPT, b64)))
    return {"folder": folder.as_posix(), "files": saved}


def assess_for_fast_agent(task: str) -> dict | None:
    try:
        verdict = core.router.assess_agent_task(task)
    except Exception as exc:
        log.warning("No se pudo valorar si la tarea es compleja: %s", exc)
        return None
    return {"task": task, "reason": verdict["reason"]} if verdict["complex"] else None


class AgentQuestionReply(BaseModel):
    answers: list[list[str]]


class AgentPermissionReply(BaseModel):
    reply: str


def opencode_call(fn, *args):
    try:
        return fn(CONFIG["opencode"]["base_url"], *args)
    except requests.RequestException as exc:
        return JSONResponse(
            {"detail": f"No se pudo contactar con el agente de codigo (¿esta arrancado?): {exc}"},
            status_code=502)


def owns_task(request: Request, session_id: str) -> bool:
    s = request.state.session
    return task_owners.may_use(session_id, s.get("user_id"), s.get("role") == "admin")


def _owns_request(request: Request, kind: str, request_id: str) -> bool:
    session_id = opencode_client.request_session(CONFIG["opencode"]["base_url"], kind, request_id)
    return bool(session_id) and owns_task(request, session_id)


def not_your_task() -> JSONResponse:
    return JSONResponse({"detail": "Tarea no encontrada."}, status_code=404)


def _own_tasks(request: Request, tasks):
    if isinstance(tasks, JSONResponse):
        return tasks
    return [t for t in tasks if owns_task(request, t["session_id"])]


@router.get("/agent/web-login", dependencies=[access.admin_only()])
def agent_web_login(request: Request):
    return {"user": opencode_client.AUTH[0], "password": opencode_client.AUTH[1]}
_CODE_ORDER = re.compile(
    r"^\W*(haz|hazme|crea|creame|arregla|corrige|cambia|añade|anade|agrega|implementa|escribe|refactoriza|"
    r"elimina|borra|quita|instala|actualiza|mueve|renombra|genera|pon|programa|monta|configura|migra|sube|"
    r"ejecuta|lanza|prueba|testea|optimiza|mejora|traduce|documenta|haga|hagas)\b", re.IGNORECASE)
_CODE_QUESTION = re.compile(
    r"\?\s*$|^\W*¿|¿[^?]{3,}\?|^\W*(que|qué|como|cómo|por que|por qué|porque|cual|cuál|cuales|cuáles|cuando|cuándo|donde|dónde|"
    r"quien|quién|explica|explicame|explícame|recomienda|recomiendame|recomiéndame|dime|sabes|hay|es posible|"
    r"se puede|puedo|deberia|debería|merece la pena|compara|revisa si|mira si|comprueba si)\b",
    re.IGNORECASE)


def _is_code_question(task: str) -> bool:
    first = task.strip().splitlines()[0] if task.strip() else ""
    if _CODE_ORDER.search(first):
        return False
    return bool(_CODE_QUESTION.search(task.strip()) or _CODE_QUESTION.search(first))


@router.get("/agent/tasks")
def agent_list_tasks(request: Request):
    return _own_tasks(request, opencode_call(opencode_client.list_tasks))


@router.post("/agent/tasks/clear")
def agent_clear_tasks(request: Request):
    base = CONFIG["opencode"]["base_url"]
    tasks = _own_tasks(request, opencode_call(opencode_client.list_tasks, 500))
    if isinstance(tasks, JSONResponse):
        return tasks
    keep = set(opencode_client.busy_session_ids(base)) | set(opencode_client.waiting_sessions(base))
    deleted = 0
    for t in tasks:
        if t["status"] != "idle" or t["session_id"] in keep:
            continue
        try:
            opencode_client.delete_task(base, t["session_id"])
            deleted += 1
        except requests.RequestException as exc:
            log.warning("No se pudo borrar la tarea %s: %s", t["session_id"], exc)
    log.info("Historial del agente borrado: %d tareas", deleted)
    return {"borradas": deleted, "en_marcha": len(tasks) - deleted}


@router.post("/agent/tasks")
def agent_start_task(request: Request, req: AgentTaskRequest):
    if not req.task.strip():
        return JSONResponse({"detail": "Describe la tarea."}, status_code=400)
    task = req.task.strip()
    saved = routines.save_request(task) or (project_rules.add_request(task, Path(req.project))
                                            if req.project and Path(req.project).is_dir() else None)
    if saved or task.lower() == "/rutinas":
        return {"mensaje": saved or routines.listing()}
    night = night_queue.NIGHT.match(task) if req.project else None
    if night and len(night.group(1).strip()) > 3:
        later = req.model_copy(update={"task": night.group(1).strip(), "autonomo": True, "continuar": None,
                                       "plan": False})
        return {"mensaje": night_queue.queue_agent_task(lambda: agent_start_task(request, later), later.task,
                                                        request.state.session)}
    routine = routines.expand(task)
    if routine:
        task = routine[0]
    if not routine and req.continuar and owns_task(request, req.continuar) and \
            _follows_task(req.continuar, task, req.project):
        note = agent_attachments.task_note(req.attachments)
        result = _continue_task(req.continuar, f"{task}\n\n{note}" if note else task,
                                ("plan" if req.plan else "build") if req.project else None)
        if isinstance(result, JSONResponse):
            return result
        return {"session_id": req.continuar, "continued": True, **result}
    if req.project:
        project = Path(req.project)
        if not project.is_dir():
            return JSONResponse({"detail": f"No existe la carpeta {req.project}."}, status_code=400)
        question = _is_code_question(task) or code_checks.remember_request(task) is not None
        plan = req.plan or question or bool(routine and routine[1])
        big = not plan and code_checks.is_big_task(task)
        new_context = not plan and not code_checks.project_has_context(project)
        if new_context:
            task += code_checks.context_created_note()
        task += (agent_watch.code_facts(task, project) + agent_watch.project_map_note(project) + lessons.note(req.task)
                 + agent_guard.teach_note(req.task))
        note = agent_attachments.task_note(req.attachments)
        if note:
            task += f"\n\n{note}\nSi son imagenes, miralas con chati_ver_imagen antes de responder."
        agent = CONFIG["opencode"]["agent_code_plan" if (plan or big) else "agent_code"]
        model = CONFIG["opencode"]["model"] if req.rapido or (question and not req.plan) else None
        copy = None if plan else checkpoints.take(project, req.task.strip())
        branch = None if plan or question else project_git.start_branch(project, req.task.strip())
        if new_context:
            try:
                (project / code_checks.CONTEXT_FILE).write_text(code_checks.context_skeleton(project),
                                                                encoding="utf-8")
            except OSError as exc:
                log.warning("No se pudo crear %s en %s: %s", code_checks.CONTEXT_FILE, project, exc)
        result = opencode_call(opencode_client.start_task, task, agent, str(project), model)
        if isinstance(result, JSONResponse):
            return result
        task_owners.record(result, request.state.session["user_id"])
        if not plan:
            agent_watch.estimates[result] = trajectories.estimate(req.task, "codigo")
        if copy:
            checkpoints.record(result, project, copy, req.task.strip())
        if branch:
            agent_watch.task_branches[result] = (branch, req.task.strip())
        agent_watch.start_code_watch(result, project, big, req.autonomo, only_look=plan)
        return {"session_id": result}
    if not req.potente and not req.confirmed:
        choice = assess_for_fast_agent(task)
        if choice:
            return {"needs_choice": True, **choice, "attachments": req.attachments}
    agent = CONFIG["opencode"]["agent_potente" if req.potente else "agent"]
    note = agent_attachments.task_note(req.attachments)
    task += prefetch.facts(task) + lessons.note(task) + agent_guard.teach_note(task)
    result = opencode_call(opencode_client.start_task, f"{task}\n\n{note}" if note else task, agent)
    if isinstance(result, JSONResponse):
        return result
    task_owners.record(result, request.state.session["user_id"])
    agent_watch.estimates[result] = trajectories.estimate(req.task, "agente")
    agent_watch.start_agent_watch(result)
    return {"session_id": result}


@router.get("/agent/tasks/{session_id}")
def agent_task_view(request: Request, session_id: str):
    if not owns_task(request, session_id):
        return not_your_task()
    return opencode_call(_task_view, session_id)


def _task_view(base_url: str, session_id: str) -> dict:
    view = opencode_client.get_task_view(base_url, session_id)
    task_model = view.get("model") or CONFIG["opencode"]["model"]
    view["model_loading"] = view["status"] != "idle" and task_model not in ollama.running_models()
    watch = agent_watch.code_watch.get(session_id) or {}
    view["verificacion"] = watch.get("estado", "") or agent_watch.agent_verification.get(session_id, "")
    if not view["verificacion"] and session_id in agent_watch.code_watch_running and not watch.get("solo_mirar"):
        view["verificacion"] = "Comprobando el trabajo…"
    view["deshacer"] = checkpoints.available(session_id)
    for perm in view.get("permissions", []):
        if perm.get("permission") == "bash":
            affected = agent_guard.affected_files(" ".join(perm.get("patterns") or []), view.get("directory"))
            if affected is not None:
                perm["afectados"] = affected
    view["prevision"] = agent_watch.estimates.get(session_id, "")
    stuck_since = agent_watch.stalled.get(session_id)
    view["atascada_min"] = int(time.time() - stuck_since) // 60 if stuck_since else 0
    view["modelo_ahora"] = llm_status.snapshot() if view["status"] != "idle" else None
    return view
LIVE_THROTTLE = 0.3


@router.get("/agent/tasks/{session_id}/live")
def agent_task_live(request: Request, session_id: str):
    if not owns_task(request, session_id):
        return not_your_task()
    base = CONFIG["opencode"]["base_url"]
    marker = session_id.encode()

    writing = {"part": None, "text": ""}

    def snapshot() -> str:
        view = _task_view(base, session_id)
        if writing["text"] and view["status"] != "idle":
            view["streaming_text"] = writing["text"]
        return f"data: {json.dumps(view, ensure_ascii=False)}\n\n"

    def track_text(event: dict) -> None:
        props = event.get("properties") or {}
        if event.get("type") == "message.part.delta" and props.get("field") == "text":
            if props.get("partID") != writing["part"]:
                writing.update(part=props.get("partID"), text="")
            writing["text"] += props.get("delta", "")
        elif event.get("type") == "message.part.updated":
            part = props.get("part") or {}
            if part.get("id") == writing["part"] and part.get("text"):
                writing.update(part=None, text="")

    def events():
        try:
            yield snapshot()
            last = 0.0
            with requests.get(f"{base}/event", stream=True, timeout=(5, 60), auth=opencode_client.AUTH,
                              **opencode_client._sparams(base, session_id)) as upstream:
                for line in upstream.iter_lines():
                    if not line.startswith(b"data:"):
                        continue
                    if marker not in line:
                        if b"server.heartbeat" in line:
                            yield ": ping\n\n"
                        continue
                    try:
                        track_text(json.loads(line[5:]))
                    except ValueError:
                        pass
                    bursty = b"message.part.delta" in line or (
                        b"message.part.updated" in line and b'"status":"running"' in line)
                    if bursty and time.time() - last < LIVE_THROTTLE:
                        continue
                    last = time.time()
                    yield snapshot()
        except requests.RequestException:
            pass
        yield "event: end\ndata: {}\n\n"

    return StreamingResponse(events(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"})


@router.get("/agent/tasks/{session_id}/changes")
def agent_task_changes(request: Request, session_id: str):
    if not owns_task(request, session_id):
        return not_your_task()
    return opencode_call(opencode_client.get_changes, session_id)


@router.post("/agent/tasks/{session_id}/revert")
def agent_task_revert(request: Request, session_id: str):
    if not owns_task(request, session_id):
        return not_your_task()
    if not opencode_client.workdir_undoable():
        return JSONResponse({"detail": "No se puede deshacer: falta git en este equipo."}, status_code=400)
    result = opencode_call(opencode_client.revert_task, session_id)
    return result if isinstance(result, JSONResponse) else {"ok": True}


@router.post("/agent/tasks/{session_id}/unrevert")
def agent_task_unrevert(request: Request, session_id: str):
    if not owns_task(request, session_id):
        return not_your_task()
    result = opencode_call(opencode_client.unrevert_task, session_id)
    return result if isinstance(result, JSONResponse) else {"ok": True}
RETRY_MESSAGE = ("[Chati] Tu ultima respuesta se quedo colgada y la he cortado. Sigue con la tarea donde lo "
                 "dejaste: no repitas lo que ya esta hecho.")


@router.post("/agent/tasks/{session_id}/retry")
def agent_retry(request: Request, session_id: str):
    if not owns_task(request, session_id):
        return not_your_task()
    watch = agent_watch.code_watch.get(session_id) if session_id in agent_watch.code_watch_running else None
    if watch:
        watch["pausa_hasta"] = time.time() + 30
    if session_id in agent_watch.code_watch:
        agent = CONFIG["opencode"]["agent_code_plan" if (watch or {}).get("solo_mirar") else "agent_code"]
    else:
        agent = CONFIG["opencode"]["agent"]
    result = opencode_call(opencode_client.abort, session_id)
    if isinstance(result, JSONResponse):
        return result
    time.sleep(1)
    result = opencode_call(opencode_client.continue_task, session_id, RETRY_MESSAGE, agent)
    if isinstance(result, JSONResponse):
        return result
    agent_watch.stalled.pop(session_id, None)
    log.info("Tarea %s atascada: reintentada por el usuario", session_id)
    return {"ok": True}


@router.post("/agent/tasks/{session_id}/abort")
def agent_abort(request: Request, session_id: str):
    if not owns_task(request, session_id):
        return not_your_task()
    result = opencode_call(opencode_client.abort, session_id)
    return result if isinstance(result, JSONResponse) else {"ok": True}


class AgentShortcutsRequest(BaseModel):
    shortcuts: list[dict]


@router.get("/agent/shortcuts")
def agent_get_shortcuts(request: Request):
    session = request.state.session
    return profile_store.get_agent_shortcuts(session["user_id"], session["dek"], session["key_generation"])


@router.put("/agent/shortcuts")
def agent_save_shortcuts(request: Request, req: AgentShortcutsRequest):
    session = request.state.session
    try:
        return profile_store.save_agent_shortcuts(req.shortcuts, session["user_id"], session["dek"],
                                                  session["key_generation"])
    except ValueError as exc:
        return JSONResponse({"detail": str(exc)}, status_code=400)
_code_store = web_tools.EncryptedStore("code_meta.json")
MAX_RECENT_PROJECTS = 10
_PICK_FOLDER_SCRIPT = (
    "import tkinter as tk\nfrom tkinter import filedialog\n"
    "root = tk.Tk(); root.withdraw(); root.attributes('-topmost', True)\n"
    "print(filedialog.askdirectory(title='Elige la carpeta del proyecto', mustexist=True) or '')\n")


class CodeProjectRequest(BaseModel):
    path: str


def _project_info(path: str) -> dict:
    p = Path(path)
    if not p.is_dir():
        return {"path": path, "exists": False}
    try:
        entries = sorted((e.name + ("/" if e.is_dir() else "") for e in p.iterdir()
                          if not e.name.startswith(".")), key=str.lower)
    except OSError:
        entries = []
    return {"path": str(p), "name": p.name or str(p), "exists": True, "git": (p / ".git").exists(),
            "agents_md": (p / "AGENTS.md").exists(), "entries": entries[:60], "total": len(entries)}


@router.post("/code/pick_folder")
def code_pick_folder(request: Request):
    try:
        out = subprocess.run([sys.executable, "-c", _PICK_FOLDER_SCRIPT], capture_output=True, check=False, text=True,
                             timeout=600, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except subprocess.TimeoutExpired:
        return {"path": None}
    path = out.stdout.strip()
    return {"path": str(Path(path)) if path else None}


@router.get("/code/projects")
def code_recent_projects(request: Request):
    session = request.state.session
    recent = _code_store.load("code_projects", session["user_id"], session["dek"], session["key_generation"], [])
    return {"projects": [_project_info(p) for p in recent]}


@router.post("/code/projects")
def code_open_project(request: Request, req: CodeProjectRequest):
    session = request.state.session
    info = _project_info(req.path.strip())
    if not info["exists"]:
        return JSONResponse({"detail": "Esa carpeta no existe."}, status_code=400)
    uid, dek, gen = session["user_id"], session["dek"], session["key_generation"]
    recent = [p for p in _code_store.load("code_projects", uid, dek, gen, []) if p != info["path"]]
    _code_store.save("code_projects", ([info["path"]] + recent)[:MAX_RECENT_PROJECTS], uid, dek, gen)
    return info


@router.post("/code/git_init")
def code_git_init(request: Request, req: CodeProjectRequest):
    p = Path(req.path)
    if not p.is_dir():
        return JSONResponse({"detail": "Esa carpeta no existe."}, status_code=400)
    if not (p / ".git").exists():
        out = subprocess.run(["git", "init", "-q", "--", str(p.resolve())], capture_output=True, check=False, text=True,
                             creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        if out.returncode != 0:
            return JSONResponse({"detail": f"git no pudo: {out.stderr.strip()}"}, status_code=400)
    return _project_info(str(p))


@router.get("/code/tasks")
def code_tasks(request: Request, path: str):
    return _own_tasks(request, opencode_call(opencode_client.list_tasks, 20, path))


class AgentFollowUp(BaseModel):
    text: str
    code_mode: str | None = None


@router.post("/agent/tasks/{session_id}/undo")
def agent_undo(request: Request, session_id: str):
    if not owns_task(request, session_id):
        return not_your_task()
    if session_id in opencode_client.busy_session_ids(CONFIG["opencode"]["base_url"]):
        return JSONResponse({"detail": "El agente sigue trabajando: paralo antes de deshacer."}, status_code=409)
    result = checkpoints.undo(session_id)
    if not result["ok"]:
        return JSONResponse({"detail": result["detail"]}, status_code=400)
    log.info("Modo Codigo: deshecho '%s' (%d archivos)", result["encargo"][:60], len(result["archivos"]))
    return result


@router.post("/agent/tasks/{session_id}/message")
def agent_continue(request: Request, session_id: str, req: AgentFollowUp):
    if not owns_task(request, session_id):
        return not_your_task()
    if not req.text.strip():
        return JSONResponse({"detail": "Escribe que quieres que haga."}, status_code=400)
    return _continue_task(session_id, req.text, req.code_mode)


def _follows_task(session_id: str, message: str, project: str | None) -> bool:
    base = CONFIG["opencode"]["base_url"]
    try:
        if session_id in opencode_client.busy_session_ids(base) or session_id in opencode_client.waiting_sessions(base):
            return False
        folder = opencode_client.session_dir(base, session_id)
        summary = opencode_client.task_summary(base, session_id)
    except requests.RequestException:
        return False
    if project:
        return bool(folder) and Path(folder).resolve() == Path(project).resolve()
    if session_id in agent_watch.code_watch:
        return False
    try:
        return core.router.same_task(summary, message)
    except Exception as exc:
        log.warning("No se pudo valorar si el mensaje sigue la tarea: %s", exc)
        return True


def _continue_task(session_id: str, text: str, code_mode: str | None):
    agent = None
    requested_mode = code_mode
    if code_mode == "plan" and code_checks.is_approval(text):
        code_mode = "build"
    if code_mode in ("plan", "build"):
        agent = CONFIG["opencode"]["agent_code_plan" if code_mode == "plan" else "agent_code"]
    elif complex_hint(text):
        agent = CONFIG["opencode"]["agent_potente"]
    request_text = text.strip()
    text = request_text
    preference = agent_guard.standing_correction(request_text)
    if preference:
        saved = agent_tools.memory_save(f"Preferencia: {preference[:50]}", preference, "preferencia")
        log.info("Preferencia del usuario guardada: %s (%s)", preference, saved)
    if code_mode == "build" and requested_mode == "plan":
        text = (f"{text}\n\n[Chati] El usuario ha elegido. Hazlo ahora paso a paso, marcando cada paso con "
                "todowrite, y comprueba con los tests al final.")
    folder = opencode_client.session_dir(CONFIG["opencode"]["base_url"], session_id) if code_mode else None
    if folder and Path(folder).is_dir():
        text += agent_watch.code_facts(text, Path(folder))
        if code_mode == "build":
            checkpoints.snapshot(session_id, Path(folder), request_text)
    result = opencode_call(opencode_client.continue_task, session_id, text, agent)
    if isinstance(result, JSONResponse):
        return result
    if not code_mode:
        agent_watch.start_agent_watch(session_id)
    if code_mode in ("plan", "build") and folder and Path(folder).is_dir():
        watch = agent_watch.code_watch.get(session_id) if session_id in agent_watch.code_watch_running else None
        if watch:
            watch["pausa_hasta"] = time.time() + 20
            if code_mode == "build":
                watch["solo_mirar"], watch["construir"] = False, True
        else:
            agent_watch.start_code_watch(session_id, Path(folder), False, only_look=code_mode == "plan")
    return {"ok": True, "mode": code_mode}


@router.post("/agent/questions/{request_id}")
def agent_reply_question(request: Request, request_id: str, req: AgentQuestionReply):
    if not _owns_request(request, "question", request_id):
        return not_your_task()
    result = opencode_call(opencode_client.reply_question, request_id, req.answers)
    return result if isinstance(result, JSONResponse) else {"ok": True}


@router.post("/agent/questions/{request_id}/reject")
def agent_reject_question(request: Request, request_id: str):
    if not _owns_request(request, "question", request_id):
        return not_your_task()
    result = opencode_call(opencode_client.reject_question, request_id)
    return result if isinstance(result, JSONResponse) else {"ok": True}


@router.post("/agent/permissions/{request_id}")
def agent_reply_permission(request: Request, request_id: str, req: AgentPermissionReply):
    if req.reply not in ("once", "always", "reject", "carpeta"):
        return JSONResponse({"detail": "Respuesta invalida."}, status_code=400)
    if not _owns_request(request, "permission", request_id):
        return not_your_task()
    if req.reply == "carpeta":
        base = CONFIG["opencode"]["base_url"]
        sid = opencode_client.request_session(base, "permission", request_id)
        view = opencode_call(opencode_client.get_task_view, sid) if sid else None
        perm = next((p for p in (view or {}).get("permissions", []) if p["id"] == request_id), None) \
            if isinstance(view, dict) else None
        path = agent_guard.edited_file(perm, view.get("directory")) if perm else None
        if path is None:
            return JSONResponse({"detail": "Ese permiso no es para cambiar un archivo."}, status_code=400)
        agent_watch.agent_allowed.setdefault(sid, set()).add(path.parent.resolve())
        log.info("Modo Agente: permitido todo en %s para la tarea %s", path.parent, sid)
        agent_watch.start_agent_watch(sid)
    result = opencode_call(opencode_client.reply_permission, request_id,
                            "once" if req.reply == "carpeta" else req.reply)
    return result if isinstance(result, JSONResponse) else {"ok": True}
