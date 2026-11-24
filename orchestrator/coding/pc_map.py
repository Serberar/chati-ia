import json
import logging
import os
import re
import shutil
import subprocess
import time
import winreg
from pathlib import Path

_logger = logging.getLogger(__name__)

REFRESH_SECONDS = 24 * 3600
TOOLS = ("git", "node", "npm", "pyinstaller", "ollama", "docker", "code", "pwsh", "winget", "java", "dotnet")
_SHELL_FOLDERS = {"Escritorio": "Desktop", "Documentos": "Personal",
                  "Descargas": "{374DE290-123F-4565-9164-39C4925E467B}"}
_cache: tuple[float, str] | None = None


def known_folders() -> dict[str, str]:
    found = {}
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                            r"Software\Microsoft\Windows\CurrentVersion\Explorer\User Shell Folders") as key:
            for name, value in _SHELL_FOLDERS.items():
                try:
                    found[name] = os.path.expandvars(winreg.QueryValueEx(key, value)[0])
                except OSError:
                    _logger.debug("known_folders: se sigue sin ello", exc_info=True)
    except OSError:
        _logger.debug("known_folders: se sigue sin ello", exc_info=True)
    home = Path.home()
    for name, default in (("Escritorio", "Desktop"), ("Documentos", "Documents"), ("Descargas", "Downloads")):
        found.setdefault(name, str(home / default))
    return {k: Path(v).as_posix() for k, v in found.items()}


def pythons() -> list[str]:
    try:
        out = subprocess.run(["py", "-0p"], capture_output=True, text=True, timeout=10, check=False,
                             creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0)).stdout
    except (OSError, subprocess.SubprocessError):
        out = ""
    found = [f"{m.group(1)}{' (el de por defecto)' if m.group(2) else ''} en {Path(m.group(3)).as_posix()}"
             for m in re.finditer(r"-V:(\S+)\s+(\*)?\s*(\S.*\.exe)", out)]
    if not found and shutil.which("python"):
        found.append(f"python en {Path(shutil.which('python')).as_posix()}")
    return found


def summary() -> str:
    global _cache
    if _cache and time.time() - _cache[0] < REFRESH_SECONDS:
        return _cache[1]
    folders = ", ".join(f"{k}: {v}" for k, v in known_folders().items())
    tools = [t for t in TOOLS if shutil.which(t)]
    missing = [t for t in TOOLS if t not in tools]
    text = (f"Mapa del equipo (comprobado por Chati, fiate de esto): {folders}. "
            f"Python: {'; '.join(pythons()) or 'no hay ninguno instalado'}. "
            f"En el PATH: {', '.join(tools) or 'nada de lo habitual'}"
            + (f"; NO estan instalados: {', '.join(missing)}." if missing else ".")
            + " La consola es Windows PowerShell 5.1: no uses && (separa con ;).")
    found = projects([Path(p) for p in known_folders().values()])
    if found:
        text += " Proyectos del usuario: " + "; ".join(found) + "."
    _cache = (time.time(), text)
    return text


_SKIP_DIRS = {"node_modules", "venv", ".venv", "env", "__pycache__", "dist", "build", "site-packages", "ComfyUI"}
MAX_PROJECTS = 15
SCAN_SECONDS = 3


def _how_to_test(folder: Path) -> str:
    if (folder / "package.json").exists():
        try:
            scripts = json.loads((folder / "package.json").read_text(encoding="utf-8")).get("scripts") or {}
        except (OSError, ValueError):
            scripts = {}
        return "npm test" if "test" in scripts else "node"
    if (folder / "tests").is_dir() or any(folder.glob("test_*.py")) or any(folder.glob("*/tests")):
        return "python -m pytest"
    return "python"


def projects(roots: list[Path], depth: int = 4) -> list[str]:
    markers = (".git", "pyproject.toml", "requirements.txt", "package.json")
    deadline = time.time() + SCAN_SECONDS
    found: list[str] = []
    pending = [(root, 0) for root in roots]
    while pending and len(found) < MAX_PROJECTS and time.time() < deadline:
        folder, level = pending.pop(0)
        try:
            entries = list(os.scandir(folder))
        except OSError:
            continue
        names = {e.name for e in entries}
        if level and any(m in names for m in markers):
            found.append(f"{folder.name} en {folder.as_posix()} (prueba: {_how_to_test(folder)})")
            continue
        if level < depth:
            pending += [(Path(e.path), level + 1) for e in entries
                        if e.is_dir(follow_symlinks=False) and not e.name.startswith(".") and e.name not in _SKIP_DIRS]
    return found
