import json
import logging
import time
from pathlib import Path

from accounts import push, task_owners
from coding import checkpoints, code_checks
from infra.paths import DATA_DIR

log = logging.getLogger("chati")
STATE_FILE = DATA_DIR / "vigilancia_proyectos.json"
RECENT_DAYS = 30
RUN_HOUR = 5


def recent_projects() -> dict[Path, str | None]:
    projects: dict[Path, str | None] = {}
    for session_id, entries in checkpoints._load().items():
        for entry in entries:
            folder = Path(entry["carpeta"])
            if time.time() - entry.get("hora", 0) < RECENT_DAYS * 86400 and folder.is_dir():
                projects[folder] = task_owners.owner(session_id) or projects.get(folder)
    return projects


def check_all() -> list[tuple[str | None, str]]:
    try:
        state = json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        state = {}
    warnings = []
    for folder, user in recent_projects().items():
        try:
            result = code_checks.run_tests(folder)
        except Exception as exc:
            log.warning("Vigilancia: no se pudieron pasar los tests de %s: %s", folder, exc)
            continue
        if result is None:
            continue
        key = str(folder)
        if state.get(key) is True and not result[0]:
            failing = sorted(code_checks.failing_tests(result[1]))
            warnings.append((user, f"{folder.name}: han dejado de pasar los tests"
                                   + (f" ({', '.join(t.split('::')[-1] for t in failing[:3])})" if failing else "")))
        state[key] = result[0]
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps(state, ensure_ascii=False, indent=1), encoding="utf-8")
    return warnings


def run_forever(busy=lambda: False) -> None:
    last_day = None
    while True:
        now = time.localtime()
        if now.tm_hour == RUN_HOUR and now.tm_yday != last_day and not busy():
            last_day = now.tm_yday
            for user, text in check_all():
                log.info("Vigilancia de proyectos: %s", text)
                if user:
                    push.notify(user, "🔎 Vigilancia de proyectos", text, tag="chati-vigilancia")
        time.sleep(300)
