import json
import re
import threading
import time

from coding.agent_guard import RUNS_SOMETHING
from infra.paths import DATA_DIR

LESSONS_FILE = DATA_DIR / "agente_lecciones.json"
MAX_LESSONS = 300
_lock = threading.Lock()
_WORD = re.compile(r"[a-záéíóúñü0-9_]{4,}", re.IGNORECASE)
_COMMON = {"arreglalo", "arregla", "funciona", "programa", "carpeta", "escritorio", "archivo", "error", "quiero",
           "hacer", "tiene", "pruebas", "cuando", "python", "ejecutarlo", "ejecutar", "sale", "abrirlo"}


def _load() -> list[dict]:
    try:
        return json.loads(LESSONS_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []


def words(text: str) -> set[str]:
    return {w.lower() for w in _WORD.findall(text)} - _COMMON


def failed_then_fixed(steps: list[dict]) -> str | None:
    error = None
    fixed = False
    for s in steps:
        if s.get("kind") != "tool" or s.get("status") not in ("completed", "error"):
            continue
        tool, out = s.get("tool", ""), (s.get("output") or s.get("error") or "")
        if "probar_programa" in tool or (tool == "bash" and RUNS_SOMETHING.search(s.get("detail") or "")):
            ok = out.lstrip().startswith("BIEN") if "probar_programa" in tool else s.get("exit") == 0
            if ok and error:
                fixed = True
            elif not ok:
                error, fixed = out.strip()[-800:] or "fallo sin salida", False
    return error if fixed else None


def extraction_messages(task: str, error: str, summary: str) -> list[dict]:
    return [{"role": "user", "content": (
        "Un agente ha resuelto esta tarea en un ordenador Windows despues de un fallo. Escribe UNA sola linea en "
        "español con la leccion reutilizable para otra vez: el sintoma, la causa y el arreglo, sin nombres de "
        "archivos ni rutas concretas de esta tarea. Ejemplo: \"Un .exe de PyInstaller --windowed que usa input() "
        "se cierra al abrirlo: hacerle una ventana con tkinter o compilarlo con consola.\" Si no hay nada "
        "reutilizable, responde solo NADA.\n\n"
        f"Tarea: {task[:600]}\n\nError que salio:\n{error[-800:]}\n\nComo lo explico el agente al terminar:\n"
        f"{summary[-1200:]}")}]


SKILL_MIN_TOOLS = 6


def skill_worthy(steps: list[dict]) -> bool:
    return sum(1 for s in steps if s.get("kind") == "tool") >= SKILL_MIN_TOOLS and failed_then_fixed(steps) is None


def skill_messages(task: str, steps: list[dict], summary: str) -> list[dict]:
    done = [f"{s.get('tool')}: {(s.get('detail') or '')[:100]}" for s in steps
            if s.get("kind") == "tool" and s.get("status") == "completed"][:25]
    return [{"role": "user", "content": (
        "Un agente ha resuelto bien esta tarea en un ordenador Windows. Escribe UNA sola linea en español con el "
        "procedimiento reutilizable para tareas del mismo tipo: \"Para <tipo de tarea>: 1) ... 2) ... 3) ...\" "
        "(3 a 5 pasos, con las herramientas que sirvieron, sin rutas ni nombres de esta tarea). Si es demasiado "
        "particular para reutilizarlo, responde solo NADA.\n\n"
        f"Tarea: {task[:600]}\n\nPasos que dio:\n" + "\n".join(done) + f"\n\nComo lo explico al terminar:\n"
        f"{summary[-800:]}")}]


def clean(reply: str) -> str | None:
    line = next((l.strip(" -*\"'`") for l in (reply or "").splitlines() if l.strip()), "")
    if not line or line.upper().startswith("NADA") or len(line) < 25:
        return None
    return line[:400]


def add(lesson: str, task: str) -> None:
    with _lock:
        lessons = _load()
        if any(x["leccion"] == lesson for x in lessons):
            return
        lessons.append({"leccion": lesson, "tarea": task[:200], "cuando": time.strftime("%Y-%m-%d")})
        LESSONS_FILE.parent.mkdir(parents=True, exist_ok=True)
        LESSONS_FILE.write_text(json.dumps(lessons[-MAX_LESSONS:], ensure_ascii=False, indent=1), encoding="utf-8")


def relevant(text: str, k: int = 3) -> list[str]:
    mine = words(text)
    scored = [(len(mine & words(x["tarea"] + " " + x["leccion"])), i, x["leccion"]) for i, x in enumerate(_load())]
    return [lesson for score, _, lesson in sorted(scored, reverse=True) if score >= 2][:k]


def note(text: str) -> str:
    found = relevant(text)
    if not found:
        return ""
    return ("\n\n[Lecciones de tareas anteriores parecidas (comprobadas: tenlas en cuenta si aplican)]\n- "
            + "\n- ".join(found))
