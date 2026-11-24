import json
import statistics
import time

from coding import lessons
from infra.paths import DATA_DIR

TRAJECTORIES_DIR = DATA_DIR / "agente_trayectorias"
INDEX_FILE = DATA_DIR / "agente_trayectorias.jsonl"
MAX_FILES = 2000
MIN_SIMILAR = 2


def estimate(task: str, mode: str) -> str:
    mine = lessons.words(task)
    try:
        rows = [json.loads(line) for line in INDEX_FILE.read_text(encoding="utf-8").splitlines() if line.strip()]
    except (OSError, ValueError):
        return ""
    similar = [r for r in rows[-1000:] if r.get("modo") == mode and len(mine & lessons.words(r.get("tarea", ""))) >= 3]
    if len(similar) < MIN_SIMILAR:
        return ""
    minutes = statistics.median(r["segundos"] for r in similar) / 60
    good = sum(1 for r in similar if not r.get("error") and not str(r.get("verificacion", "")).startswith("✗"))
    return (f"tareas parecidas: ~{max(1, round(minutes))} min, {good} de {len(similar)} bien")


def save(view: dict, mode: str, started: float, verification: str = "") -> None:
    TRAJECTORIES_DIR.mkdir(parents=True, exist_ok=True)
    steps = view.get("steps", [])
    record = {
        "session_id": view.get("session_id"), "modo": mode, "tarea": view.get("task", ""),
        "inicio": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(started)),
        "segundos": round(time.time() - started), "error": view.get("error"), "verificacion": verification,
        "herramientas": sum(1 for s in steps if s.get("kind") == "tool"), "pasos": steps,
    }
    path = TRAJECTORIES_DIR / f"{time.strftime('%Y%m%d-%H%M%S')}_{view.get('session_id', 'tarea')}.json"
    path.write_text(json.dumps(record, ensure_ascii=False, indent=1), encoding="utf-8")
    row = {k: record[k] for k in ("modo", "tarea", "segundos", "error", "verificacion")}
    with open(INDEX_FILE, "a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")
    old = sorted(TRAJECTORIES_DIR.glob("*.json"))
    for extra in old[:-MAX_FILES]:
        extra.unlink(missing_ok=True)


def failures(limit: int = 30) -> list[dict]:
    try:
        rows = [json.loads(line) for line in INDEX_FILE.read_text(encoding="utf-8").splitlines() if line.strip()]
    except (OSError, ValueError):
        return []
    return [r for r in rows if r.get("error") or str(r.get("verificacion", "")).startswith("✗")][-limit:]


if __name__ == "__main__":
    for row in failures():
        print(f"[{row['modo']}] {row['segundos'] // 60} min  {row['tarea'][:120]}\n    -> {row.get('error') or row['verificacion']}")
