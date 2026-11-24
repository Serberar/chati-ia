import json
import os
import re
import shutil
import subprocess
import tempfile
import time
from pathlib import Path

TEST_TIMEOUT = 600
OUTPUT_CHARS = 3000


def _python_for(folder: Path) -> str | None:
    for venv in (".venv", "venv", "env"):
        exe = folder / venv / "Scripts" / "python.exe"
        if exe.exists():
            return str(exe)
    return shutil.which("python") or shutil.which("py")


def test_command(folder: Path, python: str | None = None) -> list[str] | None:
    package = folder / "package.json"
    if package.exists():
        try:
            script = (json.loads(package.read_text(encoding="utf-8")).get("scripts") or {}).get("test", "")
        except ValueError:
            script = ""
        if script and "no test specified" not in script:
            npm = shutil.which("npm") or shutil.which("npm.cmd")
            return [npm, "test", "--silent"] if npm else None
    ignore = {"venv", ".venv", "env", "node_modules", ".git", "__pycache__"}
    has_tests = any(p.is_file() and not ignore.intersection(p.relative_to(folder).parts)
                    for pattern in ("test_*.py", "*_test.py") for p in folder.rglob(pattern))
    if has_tests:
        python = python or _python_for(folder)
        return [python, "-m", "pytest", "-q", "-p", "no:cacheprovider"] if python else None
    return None


_FAILED_TEST = re.compile(r"^(?:FAILED|ERROR) (\S+?::\S+)", re.MULTILINE)


def failing_tests(output: str) -> set[str]:
    return set(_FAILED_TEST.findall(output))


def baseline_failures(folder: Path, snapshot: Path) -> set[str] | None:
    result = run_tests(snapshot, python=_python_for(folder))
    if result is None:
        return None
    ok, output = result
    return set() if ok else failing_tests(output)


def run_tests(folder: Path, python: str | None = None) -> tuple[bool, str] | None:
    cmd = test_command(folder, python)
    if not cmd:
        return None
    fresh = tempfile.mkdtemp(prefix="chati_pyc_")
    env = {**os.environ, "PYTHONPYCACHEPREFIX": fresh, "PYTHONDONTWRITEBYTECODE": "1"}
    try:
        out = subprocess.run(cmd, cwd=folder, capture_output=True, check=False, text=True, timeout=TEST_TIMEOUT,
                             encoding="utf-8", errors="replace", env=env)
    except subprocess.TimeoutExpired:
        return False, f"Los tests no terminaron en {TEST_TIMEOUT // 60} minutos."
    except OSError as exc:
        return False, f"No se pudieron lanzar los tests ({' '.join(cmd[:3])}): {exc}"
    finally:
        shutil.rmtree(fresh, ignore_errors=True)
    text = (out.stdout + "\n" + out.stderr).strip()
    if out.returncode == 5 and "no tests ran" in text:
        return None
    return out.returncode == 0, text[-OUTPUT_CHARS:]


RUFF_RULES = "E9,F63,F7,F82"


def _ruff(folder: Path) -> list[str] | None:
    import sys
    if subprocess.run([sys.executable, "-m", "ruff", "--version"], capture_output=True, check=False).returncode == 0:
        return [sys.executable, "-m", "ruff"]
    exe = shutil.which("ruff")
    return [exe] if exe else None


def run_lint(folder: Path, changed: list[str]) -> tuple[bool, str] | None:
    py_files = [f for f in changed if f.endswith(".py") and (folder / f).exists()]
    cmd = None
    if py_files:
        ruff = _ruff(folder)
        if ruff:
            cmd = ruff + ["check", "--select", RUFF_RULES, "--output-format", "concise", "--no-cache", *py_files]
    elif any(f.endswith((".js", ".jsx", ".ts", ".tsx", ".vue")) for f in changed):
        package = folder / "package.json"
        try:
            has_lint = package.exists() and "lint" in (json.loads(package.read_text(encoding="utf-8"))
                                                       .get("scripts") or {})
        except ValueError:
            has_lint = False
        npm = shutil.which("npm") or shutil.which("npm.cmd")
        if has_lint and npm:
            cmd = [npm, "run", "lint", "--silent"]
    if not cmd:
        return None
    try:
        out = subprocess.run(cmd, cwd=folder, capture_output=True, check=False, text=True, timeout=TEST_TIMEOUT,
                             encoding="utf-8", errors="replace")
    except (subprocess.TimeoutExpired, OSError) as exc:
        return None if isinstance(exc, OSError) else (False, "El analizador no termino a tiempo.")
    return out.returncode == 0, (out.stdout + "\n" + out.stderr).strip()[-OUTPUT_CHARS:]


_DANGEROUS = re.compile(
    r"\b(rm|del|erase|rmdir|rd|Remove-Item|Clear-Content|format|shutdown|Stop-Computer|Restart-Computer|"
    r"reg|regedit|Set-ExecutionPolicy|runas|Start-Process)\b|"
    r"git\s+(push|reset\s+--hard|clean|checkout\s+--|rebase|filter-branch|branch\s+-D|tag\s+-d)|"
    r"(pip|npm|yarn|pnpm)\s+(uninstall|publish|unpublish)|"
    r"Invoke-(WebRequest|RestMethod|Expression)|\biex\b|curl\s.*\|\s*(sh|bash|iex)|>\s*[A-Za-z]:\\\\(Windows|Program)",
    re.IGNORECASE)


def auto_approvable(permission: str, patterns: list[str]) -> bool:
    if permission in ("edit", "write", "patch", "todowrite", "chati_lanzar_programa", "chati_renombrar",
                      "chati_editar_bloque", "chati_entorno_python", "chati_plantilla"):
        return True
    if permission == "bash":
        return not any(_DANGEROUS.search(p) and not _REGENERABLE_DELETE.match(p) for p in patterns)
    return False


_REGENERABLE_DELETE = re.compile(
    r"""^\s*(?:rm\s+(?:-[rf]+\s+)*|Remove-Item\s+(?:-(?:Recurse|Force)\s+)*|rmdir\s+/s\s+/q\s+|rd\s+/s\s+/q\s+)"""
    r"""(?:(["'])?(?:\./|\.\\)?(?:build|dist|__pycache__|\.pytest_cache|\.mypy_cache|\.ruff_cache|htmlcov|"""
    r"""\.coverage|\*\.pyc)\1?\s*)+(?:-(?:Recurse|Force)\s*)*$""", re.IGNORECASE)


def changed_files(before: dict, after: dict) -> list[str]:
    return [f for f, h in after.items() if before.get(f) != h]


def lint_message(output: str, attempt: int, max_attempts: int) -> str:
    return (f"Chati ha pasado el analizador de errores a los archivos que has cambiado y ha encontrado FALLOS "
            f"(aviso {attempt} de {max_attempts}): nombres sin definir, imports que no existen o errores de "
            f"sintaxis. Arreglalos y di que has cambiado.\n\nSalida del analizador:\n{output}")


def failure_message(output: str, attempt: int, max_attempts: int) -> str:
    return (f"Chati ha ejecutado los tests del proyecto despues de tus cambios y FALLAN (aviso {attempt} de "
            f"{max_attempts}). Arreglalo sin cambiar lo que comprueban los tests (salvo que el usuario lo pidiera), "
            f"vuelve a ejecutarlos y di que has cambiado. Si no sabes como arreglarlo, dilo y prepara la consulta "
            f"para copiar.\n\nSalida de los tests:\n{output}")


CONTEXT_FILE = "AGENTS.md"
_CONTEXT_SECTIONS = ("Para que sirve; Lenguaje y librerias principales; Estructura (carpetas y archivos "
                     "importantes); Como se ejecuta; Como se prueba (comando exacto de los tests); Decisiones "
                     "tomadas y por que; Convenciones (nombres, estilo)")


def project_has_context(folder: str | Path) -> bool:
    return (Path(folder) / CONTEXT_FILE).exists()


def context_update_messages(current: str, diff: str, summary: str) -> list[dict]:
    return [
        {"role": "system", "content": "Mantienes la ficha AGENTS.md de un proyecto de software. Escribes en "
                                      "español, breve y concreto. Devuelves SOLO el archivo completo en Markdown, "
                                      "sin explicaciones ni bloques ```."},
        {"role": "user", "content": f"Ficha actual:\n{current}\n\nCambios de esta tarea (diff):\n{diff or '(ninguno)'}"
                                    f"\n\nLo que dice el agente que ha hecho:\n{summary[:3000] or '(nada)'}\n\n"
                                    "Devuelve la ficha actualizada: mismos apartados "
                                    f"({_CONTEXT_SECTIONS}); cambia solo lo que ya no sea verdad, añade lo nuevo "
                                    "(funciones, archivos, comandos, decisiones y por que) y completa lo marcado "
                                    "(pendiente) SOLO si se deduce de lo anterior. En \"Como se ejecuta\" va como se arranca el "
                                    "programa, nunca el comando de los tests; si no hay programa, dejalo como esta. No inventes."},
    ]


LESSONS_SECTION = "Lecciones aprendidas"
STATUS_SECTION = "Estado de la ultima tarea"
MAX_PROJECT_LESSONS = 15


def section(text: str, title: str) -> str:
    match = re.search(rf"^## {re.escape(title)}\s*\n(.*?)(?=^## |\Z)", text, re.MULTILINE | re.DOTALL)
    return match.group(1).strip() if match else ""


def set_section(text: str, title: str, body: str) -> str:
    block = f"## {title}\n\n{body.strip()}\n\n"
    pattern = re.compile(rf"^## {re.escape(title)}\s*\n.*?(?=^## |\Z)", re.MULTILINE | re.DOTALL)
    if pattern.search(text):
        return pattern.sub(lambda _: block, text, count=1).rstrip() + "\n"
    return text.rstrip() + "\n\n" + block.rstrip() + "\n"


def project_notes(text: str, before: str, lesson: str | None, task: str, summary: str,
                  todos: list[dict]) -> str:
    lines = [line for line in (section(before, LESSONS_SECTION) or section(text, LESSONS_SECTION)).splitlines()
             if line.strip().startswith("- ")]
    if lesson and f"- {lesson}" not in lines:
        lines.append(f"- {lesson}")
    if lines:
        text = set_section(text, LESSONS_SECTION, "\n".join(lines[-MAX_PROJECT_LESSONS:]))
    rules = section(before, "Reglas de Chati")
    if rules:
        text = set_section(text, "Reglas de Chati", rules)
    pending = [t["text"] for t in todos if t.get("status") not in ("completed", "cancelled")]
    done = " ".join(summary.split())
    status = (f"- Encargo ({time.strftime('%d/%m/%Y')}): {' '.join(task.split())[:300]}\n"
              f"- Hecho: {done[:600] + ('…' if len(done) > 600 else '') or 'sin resumen del agente'}\n"
              + ("- Queda:\n" + "\n".join(f"  - {t}" for t in pending) if pending else "- Queda: nada pendiente"))
    return set_section(text, STATUS_SECTION, status)


def clean_context(text: str, current: str) -> str | None:
    text = re.sub(r"^```(?:markdown|md)?\s*|\s*```$", "", text.strip())
    if not text.startswith("# ") or text.count("\n## ") < 4 or len(text) < len(current) // 2:
        return None
    return text.rstrip() + "\n"


_APPROVAL = re.compile(
    r"^\W*((la|el|opci[oó]n|propuesta)\s*(n[uú]mero\s*)?\d+|(la|el)\s+(primera|segunda|tercera|primero|segundo|"
    r"tercero|ultima|última)|adelante|vale|venga|dale|s[ií]\b|ok\b|okay|de acuerdo|hazlo|hazla|perfecto|"
    r"me parece bien|me gusta|correcto)\b", re.IGNORECASE)
_REFUSAL = re.compile(r"\b(no|ninguna|ninguno|nada|mejor otra|otra opcion|otra opción)\b", re.IGNORECASE)


def is_approval(text: str) -> bool:
    text = text.strip()
    first = re.split(r"[,.;:]| pero ", text, maxsplit=1)[0]
    return bool(_APPROVAL.search(text)) and "?" not in text and not _REFUSAL.search(first)


_BIG = re.compile(r"\b(refactoriz\w*|reestructur\w*|migr\w*|aplicaci[oó]n (entera|completa)|desde cero|"
                  r"varios (archivos|ficheros|modulos)|todo el proyecto|nueva funcionalidad|sistema de)\b",
                  re.IGNORECASE)


_BUG = re.compile(r"\b(?:arregl\w*|corrig\w*|falla\w*|fallo|errores?|bug|no funciona|peta|se cuelga|roto|"
                  r"rompe|excepci[oó]n|traceback)\b", re.IGNORECASE)
_TEST_FILE = re.compile(r"(?:^|/)(?:tests?/|test_[^/]+\.py$|[^/]+_test\.py$|[^/]+\.(?:test|spec)\.[jt]sx?$)")


def is_bug_fix(task: str) -> bool:
    return bool(_BUG.search(task))


def touches_tests(changed: list[str]) -> bool:
    return any(_TEST_FILE.search(name.replace("\\", "/")) for name in changed)


def reproduce_request() -> str:
    return ("[Chati] Has arreglado un fallo pero no has añadido ningun test que lo demuestre. Añade uno que "
            "reproduzca el caso concreto del fallo (fallaria con el codigo de antes y pasa ahora), sin tocar los "
            "que ya habia, y vuelve a pasarlos todos. Si de verdad no se puede probar con un test, explica por que "
            "en una frase.")


def is_big_task(task: str) -> bool:
    return len(task) > 400 or bool(_BIG.search(task))


def folder_state(folder: Path) -> dict:
    import hashlib
    ignore = {"venv", ".venv", "env", "node_modules", ".git", "__pycache__", ".pytest_cache"}
    state = {}
    for p in folder.rglob("*"):
        if p.is_file() and not ignore.intersection(p.relative_to(folder).parts):
            state[p.relative_to(folder).as_posix()] = hashlib.sha1(p.read_bytes()).hexdigest()
    return state


_PKG_CONTEXT = re.compile(r"librer[ií]a|paquete|m[oó]dulo|package|library|\bpip\b|\bnpm\b|instal", re.IGNORECASE)
_PKG_NAME = re.compile(
    r"['\"`«]([A-Za-z0-9][A-Za-z0-9_.\-/@]{1,60})['\"`»]|"
    r"(?:librer[ií]a|paquete|m[oó]dulo|package|library)\s+(?:de\s+(?:python|npm|node)\s+)?"
    r"([A-Za-z0-9][A-Za-z0-9_.\-]*[\-_.0-9][A-Za-z0-9_.\-]*|[a-z][a-z0-9]{2,})|"
    r"(?:pip|npm)\s+install\s+([A-Za-z0-9@][A-Za-z0-9_.\-/]+)", re.IGNORECASE)
_NOT_PKG = {"que", "para", "con", "python", "npm", "node", "javascript", "excel", "una", "esta", "este", "cual",
            "mejor", "buena", "recomiendas", "nueva", "parecida", "como"}
_NPM_HINT = re.compile(r"\bnpm\b|node|javascript|\bjs\b|typescript|react|vue", re.IGNORECASE)


def package_mentions(text: str) -> list[tuple[str, str]]:
    if not _PKG_CONTEXT.search(text):
        return []
    eco = "npm" if _NPM_HINT.search(text) else "python"
    names = []
    for m in _PKG_NAME.finditer(text):
        name = next(g for g in m.groups() if g).strip(".")
        if name.lower() not in _NOT_PKG and name not in names and not name.endswith((".py", ".js", ".txt")):
            names.append(name)
    return [(n, eco) for n in names[:3]]


_REMEMBER = re.compile(r"^\W*(recuerda|acu[eé]rdate de|ap[uú]nta(te)?|no olvides|guarda en (la )?memoria|memoriza)\b"
                       r"\s*(que|esto|lo siguiente|de que)?\s*[:,]?\s*(?P<what>.+)", re.IGNORECASE | re.DOTALL)


def remember_request(text: str) -> str | None:
    m = _REMEMBER.match(text.strip())
    return m.group("what").strip() if m and "?" not in text and len(m.group("what").strip()) > 5 else None


_TEXT_TOOL_CALL = re.compile(r"<function=[\w.-]+>|<tool_call>|</tool_call>")
TOOL_CALL_NUDGES = 2


def broken_tool_call(steps: list[dict]) -> bool:
    last = next((s for s in reversed(steps) if s.get("kind") in ("text", "tool", "user")), None)
    return bool(last and last.get("kind") == "text" and _TEXT_TOOL_CALL.search(last.get("text", "")))


def tool_call_nudge() -> str:
    return ("[Chati] Tu ultima llamada a una herramienta ha salido como texto (<function=...>) y no se ha "
            "ejecutado. Vuelve a llamarla de verdad, como herramienta, y sigue con la tarea.")


REVIEW_MIN_LINES = 40
REVIEW_MIN_FILES = 3


def needs_review(diff: str) -> bool:
    lines = [ln for ln in diff.splitlines() if ln[:1] in "+-" and not ln.startswith(("+++", "---"))]
    files = sum(ln.startswith("diff --git") for ln in diff.splitlines())
    return len(lines) >= REVIEW_MIN_LINES or files >= REVIEW_MIN_FILES


def review_request(diff: str) -> str:
    return ("[Chati] Antes de darlo por terminado, revisa tus propios cambios como si fueran de otra persona. "
            "Busca: fallos de logica, casos que no contemplas (vacios, nulos, errores de red o de archivo), "
            "cosas que rompan lo que ya funcionaba, codigo que sobra y problemas de seguridad. Si encuentras algo, "
            "arreglalo y di que has cambiado y por que; si esta bien, dilo en una linea. No cambies nada mas."
            f"\n\nTus cambios:\n```diff\n{diff}\n```")


def ended_without_answer(steps: list[dict]) -> bool:
    last = next((s for s in reversed(steps) if s.get("kind") in ("text", "tool", "user")), None)
    return bool(last and last.get("kind") == "tool")


def answer_nudge() -> str:
    return ("[Chati] Has terminado sin contestar al usuario. Respondele ahora con lo que has encontrado o hecho, "
            "en español y concreto (nombres, versiones, archivos). No repitas lo que ya has hecho.")


_OPTION = re.compile(r"^\s*(?:[-*•]|\d+[.)]|#+)\s*\**\s*(?:opci[oó]n|alternativa)\b", re.IGNORECASE | re.MULTILINE)
_RECOMMENDS = re.compile(r"\brecomi[eé]nd|\brecomendaci[oó]n\b|\bte aconsejo\b|\byo (?:usar|elegir|har)[ií]a\b|"
                         r"\blo mejor (?:es|ser[ií]a)\b|\bmi elecci[oó]n\b", re.IGNORECASE)


def lists_without_recommending(steps: list[dict]) -> bool:
    last = next((s for s in reversed(steps) if s.get("kind") in ("text", "tool", "user")), None)
    if not last or last.get("kind") != "text":
        return False
    text = last.get("text", "")
    return len(_OPTION.findall(text)) >= 2 and not _RECOMMENDS.search(text)


def recommend_nudge() -> str:
    return ("[Chati] Has dado varias opciones sin decir cual eliges. Di cual recomiendas para su caso y por que, en "
            "1-2 frases (puedes nombrar la alternativa y cuando convendria).")


_RENAME = re.compile(r"\b(?:renombra\w*|cambia(?:r)? el nombre(?: de)?|rename)\s+(?:(?:la|el|a la|al)\s+)?"
                     r"(?:funci[oó]n|clase|variable|m[eé]todo|constante|campo)?\s*[`'\"]?([A-Za-z_]\w*)[`'\"]?\s+"
                     r"(?:a|por|to|como)\s+[`'\"]?([A-Za-z_]\w*)", re.IGNORECASE)


def rename_request(text: str) -> tuple[str, str] | None:
    m = _RENAME.search(text)
    if not m or m.group(1) == m.group(2) or m.group(1).lower() in _NOT_SYMBOL:
        return None
    return m.group(1), m.group(2)


_NOT_SYMBOL = {"archivo", "fichero", "carpeta", "proyecto", "directorio", "rama", "repo", "repositorio", "todo",
               "esto", "eso", "tabla", "columna", "pagina", "web"}


_LANGS = {".py": "Python", ".js": "JavaScript", ".jsx": "JavaScript (React)", ".ts": "TypeScript",
          ".tsx": "TypeScript (React)", ".vue": "Vue", ".java": "Java", ".cs": "C#", ".go": "Go", ".rs": "Rust",
          ".php": "PHP", ".rb": "Ruby", ".kt": "Kotlin", ".swift": "Swift", ".cpp": "C++", ".c": "C",
          ".html": "HTML", ".css": "CSS", ".sql": "SQL", ".ps1": "PowerShell"}
_SKELETON_SKIP = {"venv", ".venv", "env", "node_modules", ".git", "__pycache__", "dist", "build", ".pytest_cache",
                  ".mypy_cache", ".ruff_cache", ".idea", ".vscode"}


def _run_hint(folder: Path) -> str:
    package = folder / "package.json"
    if package.exists():
        try:
            scripts = (json.loads(package.read_text(encoding="utf-8")).get("scripts") or {})
        except ValueError:
            scripts = {}
        for name in ("dev", "start", "serve"):
            if name in scripts:
                return f"`npm run {name}` ({scripts[name]})"
    for name, how in (("manage.py", "`python manage.py runserver`"), ("main.py", "`python main.py`"),
                      ("app.py", "`python app.py`"), ("index.html", "abrir `index.html` en el navegador")):
        if (folder / name).exists():
            return how
    return "No tiene un programa que arrancar (por lo que se ve, es codigo que se usa desde otro sitio o desde los tests)."


def context_skeleton(folder: str | Path) -> str:
    from coding import agent_tools
    folder = Path(folder)
    counts: dict[str, int] = {}
    files = 0
    for p in folder.rglob("*"):
        rel = p.relative_to(folder).parts
        if p.is_file() and not _SKELETON_SKIP.intersection(rel):
            files += 1
            lang = _LANGS.get(p.suffix.lower())
            if lang:
                counts[lang] = counts.get(lang, 0) + 1
            if files > 5000:
                break
    langs = ", ".join(f"{name} ({n})" for name, n in sorted(counts.items(), key=lambda x: -x[1])[:5]) or "(pendiente)"
    entries = sorted((p for p in folder.iterdir() if p.name not in _SKELETON_SKIP and not p.name.startswith(".")),
                     key=lambda p: (p.is_file(), p.name.lower()))
    tree = "\n".join(f"- `{p.name}{'/' if p.is_dir() else ''}`" for p in entries[:40]) or "- (vacio)"
    try:
        deps = agent_tools._project_dependencies(folder)
    except (OSError, ValueError):
        deps = []
    deps_text = ", ".join(name for _, name, _ in deps[:25]) or "(ninguna declarada)"
    cmd = test_command(folder)
    if not cmd:
        tests = "(no tiene tests todavia)"
    else:
        tests = "`npm test`" if "npm" in Path(cmd[0]).name.lower() else "`python -m pytest`"
    readme = next((p for p in folder.glob("README*") if p.is_file()), None)
    purpose = "(pendiente)"
    if readme:
        lines = [ln.strip("# ").strip() for ln in readme.read_text(encoding="utf-8", errors="replace").splitlines()
                 if ln.strip() and not ln.startswith("![")]
        purpose = " ".join(lines[:3])[:400] or "(pendiente)"
    return (f"# {folder.name}\n\n"
            "Ficha del proyecto para quien programe en el (personas o el agente de Chati). La empezo Chati con lo "
            "que se ve desde fuera; lo marcado como pendiente se completa al trabajar en el.\n\n"
            f"## Para que sirve\n{purpose}\n\n"
            f"## Lenguaje y librerias principales\n- Lenguajes (archivos): {langs}\n- Dependencias: {deps_text}\n\n"
            f"## Estructura\n{tree}\n\n"
            f"## Como se ejecuta\n{_run_hint(folder)}\n\n"
            f"## Como se prueba\n{tests}\n\n"
            "## Decisiones tomadas y por que\n(pendiente)\n\n"
            "## Convenciones\n(pendiente)\n")


def context_created_note() -> str:
    return (f"\n\n[Nota de Chati] Este proyecto no tenia {CONTEXT_FILE}: Chati ha creado uno con lo basico "
            "(lenguajes, carpetas, dependencias, como se prueba). Leelo para situarte. NO lo completes ahora: "
            "haz directamente la tarea; al final te pedire actualizarlo.")
