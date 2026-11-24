import re
import time
from pathlib import Path

from coding import pc_map

_NAMED = re.compile(r"\b([\w\-]+\.(?:pyw?|exe|bat|cmd|ps1|js|csv|json|xlsx|txt))\b", re.IGNORECASE)
_HINT = re.compile(r"\b([\w\-]+)/([\w\-]+)\b")
_CODE = (".py", ".pyw", ".bat", ".cmd", ".ps1", ".js")
_DATA = (".csv", ".txt", ".json")
_SKIP = {"node_modules", "venv", ".venv", "env", "__pycache__", "dist", "build", "site-packages", ".git", "AppData"}
SEARCH_SECONDS = 2
MAX_CODE_CHARS = 6000


def find_named(task: str, roots: list[Path], depth: int = 5) -> list[Path]:
    names = {n.lower() for n in _NAMED.findall(task)}
    if not names:
        return []
    hints = [f"{a}/{b}".lower() for a, b in _HINT.findall(task)]
    deadline = time.time() + SEARCH_SECONDS
    found: list[Path] = []
    pending = [(r, 0) for r in roots if r.is_dir()]
    while pending and time.time() < deadline:
        folder, level = pending.pop(0)
        try:
            entries = list(folder.iterdir())
        except OSError:
            continue
        for entry in entries:
            if entry.is_file() and entry.name.lower() in names:
                found.append(entry)
            elif entry.is_dir() and level < depth and entry.name not in _SKIP and not entry.name.startswith("."):
                pending.append((entry, level + 1))
    if hints:
        found = [f for f in found if any(h in f.as_posix().lower() for h in hints)] or found
    return found


def facts(task: str, roots: list[Path] | None = None) -> str:
    roots = roots if roots is not None else [Path(p) for p in pc_map.known_folders().values()]
    files = find_named(task, roots)
    by_name: dict[str, list[Path]] = {}
    for f in files:
        by_name.setdefault(f.name.lower(), []).append(f)
    if not files or any(len(v) > 1 for v in by_name.values()):
        return ""
    parts = []
    for folder in sorted({f.parent for f in files})[:2]:
        names = sorted(p.name + ("/" if p.is_dir() else "") for p in folder.iterdir())[:40]
        parts.append(f"Carpeta {folder.as_posix()}: {', '.join(names)}")
        for item in sorted(folder.iterdir()):
            if not item.is_file():
                continue
            try:
                text = item.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            if item.suffix.lower() in _CODE and len(text) <= MAX_CODE_CHARS:
                parts.append(f"{item.name}:\n```\n{text}\n```")
            elif item.suffix.lower() in _DATA:
                head = "\n".join(text.splitlines()[:5])[:500]
                parts.append(f"Primeras lineas de {item.name} (DATOS del usuario: no los cambies):\n```\n{head}\n```")
    return ("\n\n[Nota de Chati] Ya he mirado esto por ti, no hace falta que lo vuelvas a listar ni leer (pero si que "
            "tienes que ejecutarlo para ver el error real):\n" + "\n\n".join(parts))
