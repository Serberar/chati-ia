import json
import statistics
import threading
import time

from infra.paths import DATA_DIR

TIMES_FILE = DATA_DIR / "video_tiempos.jsonl"
_lock = threading.Lock()


def record(model: str | None, frames: int, width: int, height: int, seconds_taken: float) -> None:
    row = {"modelo": model or "auto", "fotogramas": frames, "ancho": width, "alto": height,
           "segundos": round(seconds_taken, 1), "cuando": time.strftime("%Y-%m-%d %H:%M")}
    with _lock:
        TIMES_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(TIMES_FILE, "a", encoding="utf-8") as f:
            f.write(json.dumps(row) + "\n")


def estimate(model: str | None, frames: int, width: int, height: int) -> float | None:
    try:
        rows = [json.loads(line) for line in TIMES_FILE.read_text(encoding="utf-8").splitlines() if line.strip()]
    except (OSError, ValueError):
        return None
    rows = [r for r in rows if r.get("modelo") == (model or "auto") and r.get("fotogramas")][-20:]
    if not rows:
        return None
    per_unit = statistics.median(r["segundos"] / (r["fotogramas"] * r["ancho"] * r["alto"]) for r in rows)
    return per_unit * frames * width * height


def say(seconds: float | None) -> str:
    if seconds is None:
        return "Generando el vídeo (la primera vez no sé cuánto tardará en este ordenador)…"
    minutes = seconds / 60
    return f"Generando el vídeo: unos {max(1, round(minutes))} min…" if minutes >= 1 else \
        "Generando el vídeo: menos de un minuto…"
