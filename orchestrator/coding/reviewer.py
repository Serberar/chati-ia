import json
import re

_GUI_ADDED = re.compile(r"^\+\s*(?:import|from)\s+(?:tkinter|customtkinter|PyQt\d|PySide\d|wx)\b", re.MULTILINE)
_ASKS_GUI = re.compile(r"ventana|interfaz|gui|bot[oó]n|pantalla|visual|tkinter", re.IGNORECASE)
_NEW_FILE = re.compile(r"^diff --git a/(\S+) b/\S+\nnew file mode", re.MULTILINE)
_BUILD_JUNK = re.compile(r"(\.exe|\.spec)$|(^|/)(dist|build)/", re.IGNORECASE)
_ASKS_EXE = re.compile(r"\bexe\b|ejecutable|compil|pyinstaller", re.IGNORECASE)


_SKIP_ADDED = re.compile(r"^\+.*(?:@pytest\.mark\.(?:skip|xfail)|@unittest\.skip|\.skipTest\(|pytest\.skip\()",
                         re.MULTILINE)
_SILENCED = re.compile(r"^\+\s*except(?:\s+(?:Exception|BaseException))?\s*(?:as \w+)?\s*:\s*(?:pass)?\s*$\n?"
                       r"(?:^\+\s*pass\s*$)?", re.MULTILINE)
_FILE_HEADER = re.compile(r"^diff --git a/(\S+) b/", re.MULTILINE)


def _not_edited(diff: str) -> set[str]:
    parts = re.split(r"(?=^diff --git )", diff, flags=re.MULTILINE)
    return {m.group(1) for p in parts if (m := _FILE_HEADER.match(p))
            and re.search(r"^(?:deleted file mode|Binary files )", p, re.MULTILINE)}


def _test_files_diff(diff: str) -> str:
    parts = re.split(r"(?=^diff --git )", diff, flags=re.MULTILINE)
    return "".join(p for p in parts if (m := _FILE_HEADER.match(p)) and re.search(r"(^|/)(test_[^/]*|[^/]*_test)\.py$|"
                                                                                     r"(^|/)tests/", m.group(1)))


def cheats(diff: str) -> list[str]:
    problems = []
    tests = _test_files_diff(diff)
    if _SKIP_ADDED.search(tests):
        problems.append("has marcado tests para saltarlos (skip/xfail): eso esconde el fallo, no lo arregla")
    removed = len(re.findall(r"^-\s*(?:assert\b|self\.assert)", tests, re.MULTILINE))
    added = len(re.findall(r"^\+\s*(?:assert\b|self\.assert)", tests, re.MULTILINE))
    if removed > added:
        problems.append(f"has quitado {removed - added} comprobacion(es) (assert) de los tests")
    silenced = [m.group(0) for m in _SILENCED.finditer(diff) if "pass" in m.group(0)]
    if silenced:
        problems.append("has añadido un 'except: pass' que silencia los errores: si falla, que se vea o se trate")
    return problems


MAX_FIX_LINES = 200
MAX_FIX_FILES = 5
_SMALL_FIX = re.compile(r"\b(?:arregl\w*|corrig\w*|falla\w*|fallo|error\w*|bug|no funciona|no va)\b", re.IGNORECASE)
_ASKS_BIG = re.compile(r"\b(?:refactori\w*|reescrib\w*|rehaz\w*|reorganiz\w*|limpia\w*|moderniz\w*|todo el "
                       r"proyecto|entero)\b", re.IGNORECASE)
_TEST_PATH = re.compile(r"(?:^|/)(?:tests?/|test_[^/]+$|[^/]+_test\.\w+$|[^/]+\.(?:test|spec)\.\w+$)")


def diff_size(diff: str) -> tuple[int, int]:
    lines, files, in_test, skip = 0, 0, False, _not_edited(diff)
    for line in diff.splitlines():
        header = _FILE_HEADER.match(line)
        if header:
            in_test = bool(_TEST_PATH.search(header.group(1))) or header.group(1) in skip
            files += not in_test
        elif not in_test and line[:1] in "+-" and not line.startswith(("+++", "---")):
            lines += 1
    return lines, files


_NAMED_FILE = re.compile(r"[\w\-.]+\.(?:py|pyw|js|ts|jsx|tsx|json|csv|txt|bat|cmd|ps1|html|css|md|ya?ml|toml|ini|"
                         r"cfg|sql)\b", re.IGNORECASE)


def out_of_scope(diff: str, requests: list[str]) -> list[str]:
    named = {n.lower() for n in _NAMED_FILE.findall(" ".join(requests))}
    if not named:
        return []
    new = set(_NEW_FILE.findall(diff)) | _not_edited(diff)
    changed = [f for f in _FILE_HEADER.findall(diff) if not _TEST_PATH.search(f) and f != "AGENTS.md" and f not in new]
    return [f for f in changed if f.rsplit("/", 1)[-1].lower() not in named]


def overreach(diff: str, requests: list[str]) -> list[str]:
    asked = " ".join(requests)
    problems = cheats(diff)
    if _GUI_ADDED.search(diff) and not _ASKS_GUI.search(asked):
        problems.append("has añadido una ventana (tkinter o similar) a un programa y el usuario no lo ha pedido: "
                        "vuelve a dejarlo como programa de consola y arregla solo el fallo")
    junk = [f for f in _NEW_FILE.findall(diff) if _BUILD_JUNK.search(f)]
    if junk and not _ASKS_EXE.search(asked):
        problems.append(f"has creado archivos de compilacion que nadie ha pedido ({', '.join(junk[:5])}): quitalos")
    lines, files = diff_size(diff)
    if _SMALL_FIX.search(asked) and not _ASKS_BIG.search(asked) and len(asked) < 300 and \
            (lines > MAX_FIX_LINES or files > MAX_FIX_FILES):
        problems.append(f"para un arreglo concreto has cambiado {lines} lineas en {files} archivos (sin contar "
                        "tests): deja solo lo necesario para el fallo y deshaz el resto (reformateos, renombres, "
                        "mejoras que nadie ha pedido)")
    outside = out_of_scope(diff, requests)
    if outside:
        problems.append(f"has cambiado {', '.join(outside[:5])}, que el encargo no nombra: si hacia falta, di en "
                        "una frase por que; si no, dejalo como estaba")
    copies = [f for f in _NEW_FILE.findall(diff) if _COPY_NAME.search(f.rsplit("/", 1)[-1])]
    if copies and not _ASKS_COPY.search(asked):
        problems.append(f"has creado una copia ({', '.join(copies[:3])}) en vez de arreglar el archivo original: el "
                        "usuario sigue usando el original. Arregla el original y borra la copia")
    return problems


_COPY_NAME = re.compile(r".[_\- ](?:fixed|fix|arreglado|corregido|nuevo|new|v\d+|copia|copy|bueno|ok)\.\w+$",
                        re.IGNORECASE)
_ASKS_COPY = re.compile(r"\bcopia\b|\bversi[oó]n nueva\b|\botro archivo\b|\bsin tocar el original\b", re.IGNORECASE)


REVIEW_PROMPT = """Eres el revisor de un agente que acaba de terminar una tarea en un ordenador
Windows. Decide si se puede dar por buena. NO arregles nada: solo juzga.

Lo que pidio el usuario:
{request}

Lo que dice el agente al terminar:
{final}

La prueba que hizo despues de su ultimo cambio (comando y salida):
{evidence}

Sus cambios:
```diff
{diff}
```

Es BUENA solo si se cumplen las tres:
1. La prueba demuestra lo que pidio el usuario, en las condiciones que el usuario
   describe (si el fallo era "desde otra carpeta", la prueba tiene que hacerse
   desde otra carpeta; si era un .exe, probar el .exe).
2. Lo que dice el agente no contradice la prueba ni promete cosas no comprobadas.
3. Ha hecho lo pedido y nada mas (sin cambiar otras cosas del programa), y lo ha
   ARREGLADO, no ha dado una lista de "posibles soluciones".

Devuelve SOLO un JSON: {{"ok": true}} o {{"ok": false, "motivo": "<en español, una o dos frases concretas: que falta comprobar o que sobra>"}}."""


def review_messages(request: str, diff: str, evidence: str, final_text: str) -> list[dict]:
    return [{"role": "user", "content": REVIEW_PROMPT.format(
        request=request[:1500], final=final_text[-1500:] or "(nada)", evidence=evidence or "(ninguna)",
        diff=diff[:8000] or "(sin cambios en archivos)")}]


def parse(reply: str) -> str | None:
    try:
        data = json.loads(reply[reply.index("{"):reply.rindex("}") + 1])
    except (ValueError, AttributeError):
        return None
    if data.get("ok") is False:
        return str(data.get("motivo") or "no esta claro que este comprobado lo que se pidio").strip()[:400]
    return None


def review_request(problems: list[str]) -> str:
    return ("[Chati] Revision antes de darlo por bueno: " + "; ".join(problems) + ". Corrigelo y vuelve a probarlo "
            "(en las condiciones que describe el usuario), o explica en una frase por que esta bien asi.")
