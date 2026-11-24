import re
from pathlib import Path

from infra.paths import DATA_DIR

ROUTINES_DIR = DATA_DIR / "rutinas"
_CALL = re.compile(r"^/([a-z0-9][\w-]{0,40})\b\s*(.*)$", re.IGNORECASE | re.DOTALL)
_SAVE = re.compile(r"^/rutina\s+([a-z0-9][\w-]{0,40})\s*:\s*(.+)$", re.IGNORECASE | re.DOTALL)

BUILTIN = {
    "revisa": (True, "Revisa el codigo SIN CAMBIAR NADA. Si es un repo git, mira lo que ha cambiado (git status y "
                     "git diff; si no hay cambios, el ultimo commit con git show). Si no, los archivos que te diga. "
                     "Busca fallos de verdad: logica, casos limite, errores sin tratar, seguridad, datos que se "
                     "pueden perder. Para cada hallazgo: archivo:linea, el problema en una frase y el arreglo "
                     "concreto. Ordenalos del mas grave al menos. Si no encuentras nada serio, dilo; no rellenes "
                     "con detalles de estilo."),
    "tests": (False, "Ejecuta los tests del proyecto. Si alguno falla, averigua por que (lee el test y el codigo) "
                     "y arreglalo en el codigo, no en el test, salvo que el test este mal. Vuelve a pasarlos todos "
                     "hasta que esten en verde y di que has cambiado."),
    "commit": (False, "Prepara un commit de los cambios actuales: mira git status y git diff, comprueba que no "
                      "hay secretos ni archivos que no deban ir (.env, venv, dist), pasa los tests si los hay y haz "
                      "el commit con un mensaje claro que diga que cambia y por que. NUNCA hagas push."),
    "prepara-release": (False, "Prepara una version nueva: pasa los tests, sube el numero de version donde este "
                               "(pyproject, package.json, __version__...), apunta los cambios en el CHANGELOG si "
                               "existe (desde el ultimo tag: git log) y haz el commit y el tag. NUNCA hagas push: "
                               "dime el comando para que lo suba yo."),
}


def _file(name: str) -> Path:
    return ROUTINES_DIR / f"{name.lower()}.md"


def save_request(text: str) -> str | None:
    match = _SAVE.match(text.strip())
    if not match:
        return None
    name, steps = match.group(1).lower(), match.group(2).strip()
    ROUTINES_DIR.mkdir(parents=True, exist_ok=True)
    _file(name).write_text(steps + "\n", encoding="utf-8")
    return f"Rutina guardada. Lánzala escribiendo /{name} (puedes añadir detrás a qué se aplica)."


def listing() -> str:
    names = sorted(set(BUILTIN) | {p.stem for p in ROUTINES_DIR.glob("*.md")} if ROUTINES_DIR.exists()
                   else BUILTIN)
    return ("Rutinas: " + ", ".join(f"/{n}" for n in names)
            + ". Para crear una: /rutina nombre: lo que tiene que hacer.")


def expand(text: str) -> tuple[str, bool] | None:
    match = _CALL.match(text.strip())
    if not match:
        return None
    name, rest = match.group(1).lower(), match.group(2).strip()
    try:
        only_look, steps = False, _file(name).read_text(encoding="utf-8").strip()
    except OSError:
        if name not in BUILTIN:
            return None
        only_look, steps = BUILTIN[name]
    return f"{steps}\n\nSe aplica a: {rest}" if rest else steps, only_look
