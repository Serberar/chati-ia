import re
from pathlib import Path

DATA_SUFFIXES = {".csv", ".tsv", ".xlsx", ".xls", ".xlsm", ".ods", ".json", ".txt", ".db", ".sqlite",
                 ".sqlite3", ".xml", ".dat"}
CONFIG_NAMES = {"package.json", "package-lock.json", "tsconfig.json", "jsconfig.json", "composer.json",
                "requirements.txt", "requirements-dev.txt", "constraints.txt", "pyrightconfig.json",
                "launch.json", "settings.json", "tasks.json", "appsettings.json", "cmakelists.txt", "license.txt"}
_KIND_WORDS = {".csv": ("csv",), ".tsv": ("tsv", "csv"), ".xlsx": ("excel", "xlsx"), ".xls": ("excel", "xls"),
               ".xlsm": ("excel", "xlsm"), ".ods": ("ods", "hoja de calculo"), ".json": ("json",),
               ".txt": ("txt",), ".db": ("base de datos",), ".sqlite": ("base de datos", "sqlite"),
               ".sqlite3": ("base de datos", "sqlite"), ".xml": ("xml",), ".dat": ("dat",)}
_EDIT_PERMISSIONS = {"edit", "write", "patch"}

_HOME = Path.home()
BROAD_FOLDERS = {p.resolve() for p in (_HOME, _HOME / "Desktop", _HOME / "Documents", _HOME / "Downloads",
                                       _HOME / "OneDrive", _HOME / "OneDrive" / "Escritorio",
                                       _HOME / "OneDrive" / "Documentos")}


def edited_file(permission: dict, directory: str | None) -> Path | None:
    if permission.get("permission") not in _EDIT_PERMISSIONS:
        return None
    raw = permission.get("filepath") or next(iter(permission.get("patterns") or []), "")
    if not raw:
        return None
    path = Path(raw)
    if not path.is_absolute():
        if not directory:
            return None
        path = Path(directory) / path
    return path


def _asked_for(path: Path, requests: list[str]) -> bool:
    text = " ".join(requests).lower().replace("\\", "/")
    if path.name.lower() in text:
        return True
    return any(re.search(rf"\b{re.escape(word)}\b", text) for word in _KIND_WORDS.get(path.suffix.lower(), ()))


def blocked_data_edit(path: Path | None, requests: list[str], task_started: float) -> bool:
    if path is None or path.suffix.lower() not in DATA_SUFFIXES or path.name.lower() in CONFIG_NAMES:
        return False
    try:
        existed = path.is_file() and path.stat().st_mtime < task_started
    except OSError:
        return False
    return existed and not _asked_for(path, requests)


_TEST_FILE = re.compile(r"(^test_.*\.py$|_test\.py$|\.(test|spec)\.[jt]sx?$)", re.IGNORECASE)
_ASKS_FOR_TESTS = re.compile(r"\btests?\b|\bpruebas? unitarias?\b", re.IGNORECASE)
_KEEP_TESTS = re.compile(r"\bsin (?:cambiar|tocar|modificar|editar) (?:los |el )?(?:tests?|pruebas)\b", re.IGNORECASE)


def blocked_test_edit(path: Path | None, requests: list[str], task_started: float) -> bool:
    if path is None or not (_TEST_FILE.search(path.name) or "tests" in {p.lower() for p in path.parts[:-1]}):
        return False
    try:
        existed = path.is_file() and path.stat().st_mtime < task_started
    except OSError:
        return False
    text = " ".join(requests)
    return existed and (_KEEP_TESTS.search(text) is not None or not _ASKS_FOR_TESTS.search(text))


_GLOBAL_PIP = re.compile(r"^\s*(?:(?:py|python3?)(?:\.exe)?\s+(?:-\d[\d.]*\s+)?-m\s+)?pip3?(?:\.exe)?\s+install\b",
                         re.IGNORECASE)
_ASKS_GLOBAL = re.compile(r"\b(?:en el sistema|global(?:mente)?|para todos)\b", re.IGNORECASE)


def global_pip_install(permission: dict, requests: list[str]) -> bool:
    return permission.get("permission") == "bash" and not _ASKS_GLOBAL.search(" ".join(requests)) and \
        any(_GLOBAL_PIP.search(p) for p in permission.get("patterns") or [])


def global_pip_message() -> str:
    return ("[Chati] He rechazado ese pip install: instalaria el paquete en el Python de todo el ordenador. Usa "
            "chati_entorno_python con la carpeta del proyecto (lo pone en su .venv) y ejecuta el programa con el python "
            "que te diga.")


def protected_test_message(path: Path) -> str:
    return (f"[Chati] He rechazado que cambies {path.name}: es un test que ya existia y el usuario no ha pedido "
            "cambiar los tests. Arregla el CODIGO para que los tests pasen tal como estan. Si de verdad el test esta "
            "mal, dilo y explica por que, sin cambiarlo.")


def rejection_message(path: Path) -> str:
    return (f"[Chati] He rechazado que cambies {path.as_posix()}: es un archivo de datos del usuario y la tarea "
            "no pide cambiarlo. No lo toques ni lo sustituyas por datos de ejemplo. Si el programa falla con esos "
            "datos, arregla el CODIGO para que los lea bien tal como estan. Si de verdad hace falta cambiar los "
            "datos, preguntaselo al usuario y explica por que.")


def user_requests(view: dict) -> list[str]:
    texts = [view.get("task") or ""] + [s.get("text", "") for s in view.get("steps", []) if s.get("kind") == "user"]
    texts = [re.split(r"\n\n\[(?:Nota de Chati|Lecciones de tareas|Chati\])", t)[0] for t in texts]
    return [t for t in texts if t and not t.startswith("[Chati]")]


_STANDING = re.compile(r"\b(?:nunca|siempre|no vuelvas a|deja de|prefiero|no me gusta que|odio que|"
                       r"a partir de ahora|de ahora en adelante|cada vez que)\b", re.IGNORECASE)


def standing_correction(text: str) -> str | None:
    text = " ".join(text.split())
    return text[:300] if _STANDING.search(text) and len(text) >= 12 else None


_PROGRAM_SUFFIXES = (".py", ".pyw", ".ps1", ".bat", ".cmd", ".js")
RUNS_SOMETHING = re.compile(r"(?<![\w.])(python|py|pytest|node|npm|powershell|pwsh|cmd)\b|\.(exe|bat|ps1|cmd)\b",
                             re.IGNORECASE)


def unproven_change(steps: list[dict]) -> str | None:
    last_edit, proof = _last_proof(steps)
    return None if proof else last_edit


def _last_proof(steps: list[dict]) -> tuple[str | None, dict | None]:
    last_edit, proof = None, None
    for s in steps:
        if s.get("kind") != "tool" or s.get("status") != "completed":
            continue
        tool, detail = s.get("tool", ""), s.get("detail") or ""
        edits = tool in ("edit", "write", "patch") or "editar_bloque" in tool
        if edits and detail.lower().endswith(_PROGRAM_SUFFIXES):
            last_edit, proof = detail, None
        elif last_edit and "probar_programa" in tool:
            proof = s if (s.get("output") or "").lstrip().startswith("BIEN") else None
        elif last_edit and tool == "bash" and RUNS_SOMETHING.search(detail):
            proof = s if s.get("exit") == 0 else None
        elif last_edit and "compilar_exe" in tool:
            proof = s if "MAL" not in (s.get("output") or "") else None
    return last_edit, proof


def evidence(steps: list[dict]) -> str:
    _, proof = _last_proof(steps)
    if not proof:
        return ""
    output = proof.get("output") or ""
    written = output.split("Lo que ha escrito:", 1)[1] if "Lo que ha escrito:" in output else ""
    said = next((l.strip() for l in written.splitlines() if l.strip() and not l.startswith("(")), "") or \
        next((l.strip() for l in output.splitlines() if l.strip()), "")
    what = proof["detail"] if proof.get("tool") == "bash" else f"{proof['tool'].removeprefix('chati_')} {proof['detail']}"
    return f"✓ Comprobado: {what[:120]}" + (f" → {said[:160]}" if said else "")


def report(steps: list[dict]) -> str:
    changed: dict[str, bool] = {}
    for s in steps:
        if s.get("kind") != "tool" or s.get("status") != "completed":
            continue
        tool, detail = s.get("tool", ""), s.get("detail") or ""
        if tool in ("edit", "write", "patch") or "editar_bloque" in tool:
            if detail:
                changed[detail] = False
            continue
        ok = (("probar_programa" in tool and (s.get("output") or "").lstrip().startswith("BIEN"))
              or (tool == "bash" and RUNS_SOMETHING.search(detail) and s.get("exit") == 0)
              or ("compilar_exe" in tool and "MAL" not in (s.get("output") or "")))
        if ok:
            whole = tool == "bash" and re.search(r"\b(?:pytest|unittest|npm (?:run )?test|tox)\b", detail)
            for name in changed:
                if whole or Path(name).name.lower() in detail.lower():
                    changed[name] = True
    if not changed:
        return ""
    programs = [n for n in changed if n.lower().endswith(_PROGRAM_SUFFIXES)]
    others = [Path(n).name for n in changed if n not in programs]
    lines = [evidence(steps)] if any(changed[n] for n in programs) else []
    proven = [Path(n).name for n in programs if changed[n]]
    unproven = [Path(n).name for n in programs if not changed[n]]
    if proven:
        lines.append("Probado después de cambiarlo: " + ", ".join(proven))
    if unproven:
        lines.append("✗ Sin comprobar: " + ", ".join(unproven))
    if others:
        lines.append("Otros archivos cambiados: " + ", ".join(others[:8]) + (" …" if len(others) > 8 else ""))
    return " · ".join(line for line in lines if line)


def proof_request(path: str, attempt: int, max_attempts: int) -> str:
    return (f"[Chati] Has cambiado {path} pero despues no lo has ejecutado con exito (aviso {attempt} de "
            f"{max_attempts}). Antes de darlo por terminado, pruebalo: con chati_probar_programa si tiene ventana o "
            "es un .exe; si es de consola, ejecutalo y mira que el resultado sea el correcto. Si falla, arreglalo. "
            "Si no se puede probar aqui, explica por que en una frase.")


_BULK_CMD = re.compile(r"\b(?:Remove-Item|Move-Item|rm|del|erase|rmdir|rd|mv|move)\b", re.IGNORECASE)
_PATH_ARG = re.compile(r"""["']([^"']*[*?][^"']*)["']|(\S*[*?]\S*)""")
MAX_AFFECTED = 40


def affected_files(command: str, cwd: str | None) -> list[str] | None:
    if not _BULK_CMD.search(command):
        return None
    match = next((m for m in _PATH_ARG.finditer(command)
                  if not (m.group(1) or m.group(2)).startswith(("-", "$"))), None)
    if not match:
        return None
    raw = (match.group(1) or match.group(2)).replace("\\", "/")
    base = Path(raw) if Path(raw).is_absolute() else Path(cwd or ".") / raw
    try:
        found = sorted(p for p in base.parent.glob(base.name))
    except (OSError, ValueError):
        return []
    names = [p.name + ("/" if p.is_dir() else "") for p in found]
    return names[:MAX_AFFECTED] + ([f"… y {len(names) - MAX_AFFECTED} mas"] if len(names) > MAX_AFFECTED else [])


def unanswered_chati_message(steps: list[dict]) -> bool:
    last = next((s for s in reversed(steps) if s.get("kind") in ("text", "tool", "user")), None)
    return bool(last and last.get("kind") == "user" and last.get("text", "").startswith("[Chati]"))


def wake_up_message() -> str:
    return ("[Chati] Sigue con la tarea teniendo en cuenta mi mensaje anterior. No la des por terminada hasta "
            "haberlo arreglado y probado.")


_TEACH = re.compile(r"ens[eé]ñame|expl[ií]camelo|expl[ií]came (?:el )?por ?qu[eé]|quiero aprender|para aprender",
                    re.IGNORECASE)


def teach_note(task: str) -> str:
    if not _TEACH.search(task):
        return ""
    return ("\n\n[Nota de Chati] El usuario quiere aprender. Al terminar, explica en 4-6 frases sencillas por que "
            "fallaba, que concepto de fondo hay (por ejemplo, que es la codificacion de un archivo) y como detectarlo "
            "la proxima vez. Sin jerga sin explicar.")


_KEEP_RUNNING = re.compile(r"\b(?:arranca(?:lo|la|me)?|lanza(?:lo|la)?|levanta(?:lo|la)?|pon(?:lo|la)? en marcha|"
                           r"d[eé]ja(?:lo|la)? (?:abiert[oa]|en marcha|funcionando|corriendo)|que se quede abiert)",
                           re.IGNORECASE)


def keeps_running(requests: list[str]) -> bool:
    return any(_KEEP_RUNNING.search(r) for r in requests)


def consult_request() -> str:
    return ("[Chati] No has conseguido que funcione y lo hayas comprobado. Para de intentarlo. Escribe en dos frases "
            "que has probado y que falla, y despues una CONSULTA LISTA PARA COPIAR, en un bloque de codigo que "
            "empiece por \"CONSULTA PARA OTRA IA:\", con: que se quiere conseguir, el lenguaje y las "
            "librerias con su version, el error exacto, el fragmento de codigo justo (sin contraseñas ni datos "
            "personales) y lo que ya has probado. Debe entenderse sin ver nada mas. No cambies mas archivos.")


LOOP_REPEATS = 3


def stuck_loop(steps: list[dict]) -> str | None:
    done = [s for s in steps if s.get("kind") == "tool" and s.get("status") in ("completed", "error")]
    last = done[-LOOP_REPEATS:]
    if len(last) < LOOP_REPEATS:
        return None
    calls = {(s.get("tool"), s.get("detail")) for s in last}
    if len(calls) == 1 and last[-1].get("detail"):
        return f"la misma llamada ({last[-1]['tool']} {last[-1]['detail'][:120]})"
    errors = {(s.get("error") or "").strip()[-200:] for s in last}
    if len(errors) == 1 and "" not in errors:
        return f"el mismo error ({errors.pop()[-120:]})"
    return None


def loop_message(what: str) -> str:
    return (f"[Chati] Llevas {LOOP_REPEATS} intentos seguidos con {what} sin avanzar. Para: repetirlo no va a "
            "cambiar el resultado. Piensa por que falla, cambia de enfoque (otro comando, mirar el error con calma, "
            "leer el codigo) y, si no sabes seguir, dilo y explica que has probado.")


def copy_folder(path: Path) -> Path | None:
    folder = path.parent
    try:
        folder = folder.resolve()
    except OSError:
        return None
    if folder in BROAD_FOLDERS or folder.parent == folder or not folder.is_dir():
        return None
    return folder
