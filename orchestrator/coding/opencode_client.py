import os
import re
import secrets
import shutil
import subprocess
from collections.abc import Callable
from pathlib import Path

import requests

from coding import pc_map
from infra import paths

TIMEOUT = 15

PASSWORD_FILE = paths.DATA_DIR / "opencode_password.txt"


def server_password() -> str:
    if PASSWORD_FILE.exists():
        existing = PASSWORD_FILE.read_text(encoding="utf-8").strip()
        if existing:
            return existing
    PASSWORD_FILE.parent.mkdir(parents=True, exist_ok=True)
    password = secrets.token_urlsafe(24)
    PASSWORD_FILE.write_text(password, encoding="utf-8")
    return password


AUTH = ("opencode", server_password())

_HOME = Path(os.environ.get("USERPROFILE") or Path.home())
SYSTEM_CONTEXT = (
    "Contexto del equipo: Windows 11, shell PowerShell. "
    f"Carpeta personal del usuario: {_HOME.as_posix()}. Escribe las rutas con barras normales (/), "
    "que Windows acepta igual. "
    "No preguntes datos que puedas averiguar tu mismo (rutas, sistema operativo, "
    "contenido de archivos) - pregunta solo si la tarea es ambigua de verdad. "
    "Responde siempre en español. Al terminar, resume en una o dos frases que has hecho."
)

before_task: Callable[[str | None], None] | None = None

WORKDIR: Path | None = None


_session_dirs: dict[str, str] = {}
_session_models: dict[str, str] = {}


def _params(directory: str | None = None) -> dict:
    d = directory or (str(WORKDIR) if WORKDIR else None)
    return {"params": {"directory": d}} if d else {}


def _dir() -> dict:
    return _params()


def session_dir(base_url: str, session_id: str) -> str | None:
    if session_id not in _session_dirs:
        try:
            resp = requests.get(f"{base_url}/session/{session_id}", auth=AUTH, timeout=TIMEOUT)
            resp.raise_for_status()
            found = resp.json().get("directory")
        except (requests.RequestException, ValueError, AttributeError):
            found = None
        if not found:
            return str(WORKDIR) if WORKDIR else None
        _session_dirs[session_id] = found
    return _session_dirs[session_id] or None


def _sparams(base_url: str, session_id: str) -> dict:
    return _params(session_dir(base_url, session_id))


def known_dirs() -> list[str | None]:
    dirs = [str(WORKDIR) if WORKDIR else None]
    for d in _session_dirs.values():
        if d and d not in dirs:
            dirs.append(d)
    return dirs


def workdir_undoable(directory: str | None = None) -> bool:
    d = Path(directory) if directory else WORKDIR
    return bool(d) and (d / ".git").exists()


def ensure_workdir() -> None:
    if not WORKDIR:
        return
    WORKDIR.mkdir(parents=True, exist_ok=True)
    if not (WORKDIR / ".git").exists() and shutil.which("git"):
        subprocess.run(["git", "init", "-q", str(WORKDIR)], check=False,
                       creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))


_HIDDEN_TOOLS = {"question", "todowrite", "todoread"}


def create_session(base_url: str, directory: str | None = None) -> str:
    if not directory:
        ensure_workdir()
    resp = requests.post(f"{base_url}/session", json={}, **_params(directory), auth=AUTH, timeout=TIMEOUT)
    resp.raise_for_status()
    session_id = resp.json()["id"]
    _session_dirs[session_id] = directory or (str(WORKDIR) if WORKDIR else "")
    return session_id


_WINDOWS_PATH = re.compile(r'[A-Za-z]:\\[^"\n<>|?*]*')


def forward_slash_paths(text: str) -> str:
    return _WINDOWS_PATH.sub(lambda m: m.group(0).replace("\\", "/"), text)


_DAYS = ("lunes", "martes", "miercoles", "jueves", "viernes", "sabado", "domingo")


def _today() -> str:
    import datetime
    d = datetime.date.today()
    return f"{_DAYS[d.weekday()]} {d.isoformat()}"


def send_prompt_async(base_url: str, session_id: str, text: str, agent: str | None = None,
                      model: str | None = None) -> None:
    system = f"{SYSTEM_CONTEXT} Hoy es {_today()}. {pc_map.summary()}"
    directory = session_dir(base_url, session_id)
    if directory and (not WORKDIR or Path(directory) != WORKDIR):
        system += (f" Estas trabajando en el proyecto de la carpeta {Path(directory).as_posix()}: "
                   "las rutas relativas son desde ahi.")
    elif WORKDIR:
        system += (f" Tu carpeta de trabajo es {WORKDIR.as_posix()}: si el usuario no dice donde "
                   "guardar algo, guardalo ahi (lo que cambies en ella se puede deshacer).")
    body = {"parts": [{"type": "text", "text": forward_slash_paths(text)}], "system": system}
    if agent:
        body["agent"] = agent
    if model:
        body["model"] = {"providerID": "ollama", "modelID": model}
    resp = requests.post(f"{base_url}/session/{session_id}/prompt_async", json=body,
                         **_params(directory), auth=AUTH, timeout=TIMEOUT)
    resp.raise_for_status()


def start_task(base_url: str, task: str, agent: str | None = None, directory: str | None = None,
               model: str | None = None) -> str:
    if before_task is not None:
        before_task(agent, model)
    session_id = create_session(base_url, directory)
    if model:
        _session_models[session_id] = model
    send_prompt_async(base_url, session_id, task, agent, model)
    return session_id


def continue_task(base_url: str, session_id: str, text: str, agent: str | None = None) -> None:
    agent = agent or _get(base_url, f"/session/{session_id}", session_id=session_id).get("agent")
    model = _session_models.get(session_id)
    if before_task is not None:
        before_task(agent, model)
    send_prompt_async(base_url, session_id, text, agent, model)


def delegate(base_url: str, task: str, agent: str | None = None) -> tuple[str, str | None]:
    try:
        session_id = start_task(base_url, task, agent)
    except requests.RequestException as exc:
        return f"No se pudo contactar con el agente de codigo (¿esta arrancado?): {exc}", None
    return (
        ("Se lo he pasado al agente. Veras aqui debajo lo que va haciendo, y te pedira "
         "permiso antes de cambiar nada. Puede tardar unos minutos."),
        session_id,
    )


def _get(base_url: str, path: str, session_id: str | None = None, directory: str | None = None):
    params = _sparams(base_url, session_id) if session_id else _params(directory)
    resp = requests.get(f"{base_url}{path}", **params, auth=AUTH, timeout=TIMEOUT)
    resp.raise_for_status()
    return resp.json()


def _tool_detail(tool: str, inp: dict) -> str:
    if tool == "bash":
        return inp.get("command", "")
    for key in ("filePath", "path", "pattern", "url", "ruta"):
        if inp.get(key):
            return str(inp[key])
    return ""


TERMINAL_MAX_CHARS = 4000
PERMISSION_DIFF_CHARS = 20000
_ANSI = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]")


def _terminal_output(state: dict) -> str:
    out = (state.get("metadata") or {}).get("output") or state.get("output") or ""
    out = _ANSI.sub("", out).replace("\r\n", "\n")
    if len(out) > TERMINAL_MAX_CHARS:
        out = "…\n" + out[-TERMINAL_MAX_CHARS:]
    return out


def _simplify_parts(messages: list) -> tuple[list, str | None]:
    steps = []
    error = None
    first_user_seen = False
    for msg in messages:
        info = msg.get("info", {})
        if info.get("role") == "user":
            if first_user_seen:
                text = " ".join(p.get("text", "") for p in msg.get("parts", []) if p.get("type") == "text").strip()
                if text:
                    steps.append({"kind": "user", "text": text})
            first_user_seen = True
            continue
        if info.get("role") != "assistant":
            continue
        if info.get("error"):
            err = info["error"]
            error = (err.get("data") or {}).get("message") or err.get("name") or "Error desconocido"
        useful = any(p.get("type") in ("text", "tool") for p in msg.get("parts", []))
        if info.get("finish") == "length" and not useful:
            error = "El modelo se ha atascado sin llegar a hacer nada. Prueba otra vez o usa el modelo potente."
        for part in msg.get("parts", []):
            text = part.get("text", "").strip().removesuffix("<tool_call>").rstrip() if part.get("type") == "text" else ""
            if text:
                steps.append({"kind": "text", "text": text})
            elif part.get("type") == "tool" and part.get("tool") not in _HIDDEN_TOOLS:
                state = part.get("state", {})
                step = {
                    "kind": "tool",
                    "tool": part.get("tool"),
                    "status": state.get("status"),
                    "title": state.get("title") or "",
                    "detail": _tool_detail(part.get("tool", ""), state.get("input") or {}),
                    "error": state.get("error"),
                }
                if part.get("tool") == "bash":
                    step["output"] = _terminal_output(state)
                    step["exit"] = (state.get("metadata") or {}).get("exit")
                elif any(t in part.get("tool", "") for t in ("probar_programa", "compilar_exe")):
                    step["output"] = _terminal_output(state)
                steps.append(step)
    return steps, error


def _latest_todos(messages: list) -> list[dict]:
    todos = []
    for msg in messages:
        for part in msg.get("parts", []):
            if part.get("type") == "tool" and part.get("tool") == "todowrite":
                found = ((part.get("state") or {}).get("input") or {}).get("todos")
                if isinstance(found, list):
                    todos = found
    return [{"text": str(t.get("content", ""))[:200], "status": t.get("status", "pending")}
            for t in todos if isinstance(t, dict) and t.get("content")][:30]


def get_task_view(base_url: str, session_id: str) -> dict:
    kw = {"session_id": session_id}
    session = _get(base_url, f"/session/{session_id}", **kw)
    statuses = _get(base_url, "/session/status", **kw)
    messages = _get(base_url, f"/session/{session_id}/message", **kw)
    questions = [q for q in _get(base_url, "/question", **kw) if q.get("sessionID") == session_id]
    permissions = [p for p in _get(base_url, "/permission", **kw) if p.get("sessionID") == session_id]

    status = statuses.get(session_id, {"type": "idle"})
    steps, error = _simplify_parts(messages)
    first_user = next((m for m in messages if m.get("info", {}).get("role") == "user"), None)
    task = " ".join(p.get("text", "") for p in (first_user or {}).get("parts", [])
                    if p.get("type") == "text").strip()
    return {
        "session_id": session_id,
        "task": task,
        "title": session.get("title", ""),
        "model": (session.get("model") or {}).get("id"),
        "status": status.get("type", "idle"),
        "retry_message": status.get("message"),
        "steps": steps,
        "todos": _latest_todos(messages),
        "error": error,
        "questions": [{"id": q["id"], "questions": q.get("questions", [])} for q in questions],
        "permissions": [{
            "id": p["id"],
            "permission": p.get("permission", ""),
            "patterns": p.get("patterns", []),
            "diff": str((p.get("metadata") or {}).get("diff") or "")[:PERMISSION_DIFF_CHARS],
            "filepath": (p.get("metadata") or {}).get("filepath") or "",
        } for p in permissions],
        "changes": _changes_summary(messages),
        "reverted": bool(session.get("revert")),
        "undoable": workdir_undoable(session_dir(base_url, session_id)),
        "directory": session_dir(base_url, session_id),
    }


def _changes_summary(messages: list) -> dict:
    files, additions, deletions = set(), 0, 0
    for msg in messages:
        info = msg.get("info", {})
        if info.get("role") == "user":
            for d in (info.get("summary") or {}).get("diffs") or []:
                files.add(d.get("file"))
                additions += d.get("additions", 0)
                deletions += d.get("deletions", 0)
    return {"files": len(files), "additions": additions, "deletions": deletions}


def list_tasks(base_url: str, limit: int = 20, directory: str | None = None) -> list:
    sessions = _get(base_url, "/session", directory=directory)
    statuses = _get(base_url, "/session/status", directory=directory)
    for s in sessions:
        _session_dirs.setdefault(s["id"], s.get("directory") or directory or (str(WORKDIR) if WORKDIR else ""))
    sessions = [s for s in sessions if not s.get("parentID")]
    sessions.sort(key=lambda s: s.get("time", {}).get("updated", 0), reverse=True)
    return [{
        "session_id": s["id"],
        "title": s.get("title", ""),
        "updated": s.get("time", {}).get("updated"),
        "status": statuses.get(s["id"], {"type": "idle"}).get("type", "idle"),
    } for s in sessions[:limit]]


def task_summary(base_url: str, session_id: str) -> str:
    title = _get(base_url, f"/session/{session_id}", session_id=session_id).get("title", "")
    if title and not title.startswith("New session"):
        return title
    for msg in _get(base_url, f"/session/{session_id}/message", session_id=session_id):
        if msg.get("info", {}).get("role") == "user":
            for part in msg.get("parts", []):
                if part.get("type") == "text" and part.get("text", "").strip():
                    text = part["text"].strip()
                    return text if len(text) <= 70 else text[:67] + "..."
    return title


def waiting_sessions(base_url: str) -> dict[str, str]:
    waiting: dict[str, str] = {}
    try:
        for directory in known_dirs():
            for path, reason in (("/permission", "permission"), ("/question", "question")):
                for item in requests.get(f"{base_url}{path}", **_params(directory), auth=AUTH, timeout=3).json():
                    waiting[item["sessionID"]] = reason
    except (requests.RequestException, ValueError, KeyError, TypeError):
        return {}
    return waiting


def stop_task(base_url: str, session_id: str) -> None:
    for question in _get(base_url, "/question", session_id=session_id):
        if question.get("sessionID") == session_id:
            reject_question(base_url, question["id"])
    for permission in _get(base_url, "/permission", session_id=session_id):
        if permission.get("sessionID") == session_id:
            reply_permission(base_url, permission["id"], "reject")
    abort(base_url, session_id)


def busy_session_ids(base_url: str) -> list[str]:
    try:
        busy = []
        for directory in known_dirs():
            kw = _params(directory)
            statuses = requests.get(f"{base_url}/session/status", **kw, auth=AUTH, timeout=3).json()
            waiting = {item["sessionID"]
                       for path in ("/question", "/permission")
                       for item in requests.get(f"{base_url}{path}", **kw, auth=AUTH, timeout=3).json()}
            busy += [sid for sid, st in statuses.items() if st.get("type") != "idle" and sid not in waiting]
        return busy
    except (requests.RequestException, ValueError, AttributeError, KeyError, TypeError):
        return []


def _post_to_owner(base_url: str, path: str, body: dict) -> None:
    resp = None
    for directory in known_dirs():
        resp = requests.post(f"{base_url}{path}", json=body, **_params(directory), auth=AUTH, timeout=TIMEOUT)
        if resp.status_code != 404:
            break
    if resp is not None:
        resp.raise_for_status()


def request_session(base_url: str, kind: str, request_id: str) -> str | None:
    for directory in known_dirs():
        try:
            items = requests.get(f"{base_url}/{kind}", **_params(directory), auth=AUTH, timeout=3).json()
        except (requests.RequestException, ValueError):
            continue
        for item in items if isinstance(items, list) else []:
            if item.get("id") == request_id:
                return item.get("sessionID")
    return None


def reply_question(base_url: str, request_id: str, answers: list[list[str]]) -> None:
    _post_to_owner(base_url, f"/question/{request_id}/reply", {"answers": answers})


def reject_question(base_url: str, request_id: str) -> None:
    _post_to_owner(base_url, f"/question/{request_id}/reject", {})


def reply_permission(base_url: str, request_id: str, reply: str) -> None:
    _post_to_owner(base_url, f"/permission/{request_id}/reply", {"reply": reply})


PATCH_MAX_CHARS = 8000


def get_changes(base_url: str, session_id: str) -> dict:
    turns = []
    for msg in _get(base_url, f"/session/{session_id}/message", session_id=session_id):
        info = msg.get("info", {})
        if info.get("role") != "user":
            continue
        diffs = (info.get("summary") or {}).get("diffs") or []
        text = " ".join(p.get("text", "") for p in msg.get("parts", []) if p.get("type") == "text").strip()
        turns.append({
            "message_id": info.get("id"),
            "text": text if len(text) <= 90 else text[:87] + "...",
            "files": [{
                "file": d.get("file", ""),
                "status": d.get("status", "modified"),
                "additions": d.get("additions", 0),
                "deletions": d.get("deletions", 0),
                "patch": (d.get("patch") or "")[:PATCH_MAX_CHARS],
            } for d in diffs],
        })
    session = _get(base_url, f"/session/{session_id}", session_id=session_id)
    directory = session_dir(base_url, session_id)
    return {"turns": turns, "reverted": bool(session.get("revert")),
            "workdir": Path(directory).as_posix() if directory else None}


def revert_task(base_url: str, session_id: str) -> None:
    messages = _get(base_url, f"/session/{session_id}/message", session_id=session_id)
    first_user = next((m for m in messages if m.get("info", {}).get("role") == "user"), None)
    if first_user is None:
        return
    resp = requests.post(f"{base_url}/session/{session_id}/revert",
                         json={"messageID": first_user["info"]["id"]}, **_sparams(base_url, session_id), auth=AUTH, timeout=60)
    resp.raise_for_status()


def unrevert_task(base_url: str, session_id: str) -> None:
    resp = requests.post(f"{base_url}/session/{session_id}/unrevert", json={},
                         **_sparams(base_url, session_id), auth=AUTH, timeout=60)
    resp.raise_for_status()


def delete_task(base_url: str, session_id: str) -> None:
    resp = requests.delete(f"{base_url}/session/{session_id}", **_sparams(base_url, session_id), auth=AUTH,
                           timeout=TIMEOUT)
    resp.raise_for_status()


def abort(base_url: str, session_id: str) -> None:
    resp = requests.post(f"{base_url}/session/{session_id}/abort", json={},
                         **_sparams(base_url, session_id), auth=AUTH, timeout=TIMEOUT)
    resp.raise_for_status()
