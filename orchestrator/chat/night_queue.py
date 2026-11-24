"""Cola nocturna: videos y encargos del agente que se hacen de madrugada."""
import re
import threading
import time
from collections.abc import Callable

from accounts import push
from coding import agent_watch
from infra.core import log

_run_chat: Callable | None = None


def configure(run_chat: Callable) -> None:
    global _run_chat
    _run_chat = run_chat


NIGHT = re.compile(r"^\s*(?:esta noche|por la noche|de noche|cola nocturna)\b[\s,.:;-]*(.*)$",
                   re.IGNORECASE | re.DOTALL)
NIGHT_HOURS = range(1, 7)
_queue: list[dict] = []
_lock = threading.Lock()


def queue_videos(message: str, session_id: str, auth_session: dict) -> str | None:
    match = NIGHT.match(message)
    items = [line.strip(" -•*\t").strip() for line in (match.group(1) if match else "").splitlines()]
    items = [i for i in items if len(i) > 3]
    if not items:
        return None
    with _lock:
        _queue.extend({"message": i, "session_id": session_id, "auth": auth_session}
                            for i in items)
        if not any(t.name == "cola-nocturna" for t in threading.enumerate()):
            threading.Thread(target=_worker, name="cola-nocturna", daemon=True).start()
    return (f"Apuntado{'s' if len(items) > 1 else ''} {len(items)} vídeo{'s' if len(items) > 1 else ''} para esta "
            f"noche (a partir de la 1:00), en esta conversación. Te aviso al móvil cuando estén. Si Chati se "
            "reinicia antes, la cola se pierde y habría que volver a pedirlos.")


def _worker() -> None:
    done: dict[str, int] = {}
    while True:
        with _lock:
            pending = bool(_queue)
        if not pending:
            for user, count in done.items():
                push.notify(user, "🎬 Vídeos de la noche listos", f"{count} vídeo(s) hechos.", tag="chati-video")
            return
        if time.localtime().tm_hour not in NIGHT_HOURS:
            time.sleep(60)
            continue
        with _lock:
            item = _queue.pop(0)
        if "start" in item:
            _task(item)
            continue
        try:
            _run_chat(item["message"], "video", item["session_id"], item["auth"])
            done[item["auth"]["user_id"]] = done.get(item["auth"]["user_id"], 0) + 1
        except Exception as exc:
            log.warning("Cola nocturna: fallo con %r: %s", item["message"][:80], exc)


def _task(item: dict) -> None:
    try:
        started = item["start"]()
    except Exception as exc:
        log.warning("Cola nocturna: no se pudo empezar el encargo: %s", exc)
        return
    session_id = started.get("session_id") if isinstance(started, dict) else None
    if not session_id:
        return
    time.sleep(5)
    deadline = time.time() + agent_watch.CODE_WATCH_HOURS * 3600
    while session_id in agent_watch.code_watch_running and time.time() < deadline:
        time.sleep(30)
    estado = (agent_watch.code_watch.get(session_id) or {}).get("estado") or "Terminado."
    push.notify(item["auth"]["user_id"], "🌙 Encargo de la noche", f"{item['task'][:60]}: {estado[:150]}",
                tag="chati-agente")


def queue_agent_task(start: Callable[[], dict], task: str, auth_session: dict) -> str:
    with _lock:
        _queue.append({"start": start, "task": task, "auth": auth_session})
        if not any(t.name == "cola-nocturna" for t in threading.enumerate()):
            threading.Thread(target=_worker, name="cola-nocturna", daemon=True).start()
    return ("Apuntado para esta noche (a partir de la 1:00), en modo «sin preguntar»: lo peligroso se quedará "
            "esperando a que lo apruebes. Si el proyecto es un repo git limpio, irá a su propia rama. Te aviso al "
            "móvil con el resultado. Si Chati se reinicia antes, se pierde.")
