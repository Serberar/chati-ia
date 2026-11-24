from pathlib import Path

ALLOWED_DIRS = [
    Path.home() / "Desktop",
    Path.home() / "Documents",
]

MAX_FILE_CHARS = 200_000
MAX_LISTING_ENTRIES = 200


def _resolve_within_allowed(ruta: str) -> Path | None:
    try:
        target = Path(ruta).expanduser().resolve()
    except (OSError, RuntimeError, ValueError):
        return None
    for allowed in ALLOWED_DIRS:
        allowed_resolved = allowed.resolve()
        if target == allowed_resolved or allowed_resolved in target.parents:
            return target
    return None


def _permission_denied_message() -> str:
    lugares = ", ".join(str(d) for d in ALLOWED_DIRS)
    return f"No tengo permiso para acceder ahi. Solo puedo leer dentro de: {lugares}."


def leer_archivo(ruta: str) -> str:
    target = _resolve_within_allowed(ruta)
    if target is None:
        return _permission_denied_message()
    if not target.exists():
        return f"No existe el archivo: {target}"
    if not target.is_file():
        return f"No es un archivo, es una carpeta: {target}"
    try:
        content = target.read_text(encoding="utf-8", errors="replace")
    except Exception as exc:
        return f"No se pudo leer el archivo: {exc}"
    if len(content) > MAX_FILE_CHARS:
        content = content[:MAX_FILE_CHARS] + "\n... (contenido truncado, el archivo es muy grande)"
    return content


def listar_carpeta(ruta: str) -> str:
    target = _resolve_within_allowed(ruta)
    if target is None:
        return _permission_denied_message()
    if not target.is_dir():
        return f"No es una carpeta: {target}"
    entries = sorted(target.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower()))
    lines = [f"{'[carpeta] ' if e.is_dir() else ''}{e.name}" for e in entries[:MAX_LISTING_ENTRIES]]
    if not lines:
        return "La carpeta esta vacia."
    return "\n".join(lines)
