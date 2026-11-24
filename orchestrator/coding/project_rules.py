import fnmatch
import re
import subprocess
from pathlib import Path

from coding import code_checks

SECTION = "Reglas de Chati"
_NO_TOUCH = re.compile(r"^-\s*no tocar\s*:\s*(.+)$", re.IGNORECASE | re.MULTILINE)
_AFTER_EDIT = re.compile(r"^-\s*al editar\s+(\S+)\s*:\s*(.+)$", re.IGNORECASE | re.MULTILINE)
_ADD = re.compile(r"^/regla\s+((?:no tocar|al editar\s+\S+)\s*:\s*.+)$", re.IGNORECASE | re.DOTALL)
COMMAND_SECONDS = 60


def _project(path: Path) -> tuple[Path, str] | None:
    for folder in list(path.parents)[:8]:
        card = folder / code_checks.CONTEXT_FILE
        if card.is_file():
            try:
                rules = code_checks.section(card.read_text(encoding="utf-8", errors="replace"), SECTION)
            except OSError:
                return None
            return (folder, rules) if rules else None
    return None


def forbidden(path: Path | None) -> str | None:
    found = _project(path) if path else None
    if not found:
        return None
    root, rules = found
    rel = path.relative_to(root).as_posix()
    for line in _NO_TOUCH.findall(rules):
        for pattern in (p.strip().strip("`") for p in line.split(",")):
            folder = pattern.rstrip("/")
            if pattern and (fnmatch.fnmatch(rel, pattern) or rel == folder or rel.startswith(folder + "/")
                            or fnmatch.fnmatch(path.name, pattern)):
                return pattern
    return None


def after_edit(path: str) -> str | None:
    file = Path(path)
    found = _project(file) if path else None
    if not found:
        return None
    root, rules = found
    failures = []
    for pattern, command in _AFTER_EDIT.findall(rules):
        if not fnmatch.fnmatch(file.name, pattern) and not fnmatch.fnmatch(file.relative_to(root).as_posix(), pattern):
            continue
        command = command.strip().strip("`").replace("{archivo}", f'"{file}"')
        try:
            out = subprocess.run(command, shell=True, cwd=root, capture_output=True, text=True,
                                 timeout=COMMAND_SECONDS, encoding="utf-8", errors="replace")
        except subprocess.TimeoutExpired:
            failures.append(f"`{command}`: no ha terminado en {COMMAND_SECONDS} s")
            continue
        if out.returncode != 0:
            failures.append(f"`{command}` falla:\n{(out.stdout + out.stderr).strip()[-1500:]}")
    return "\n".join(failures) or None


def add_request(text: str, project: Path) -> str | None:
    match = _ADD.match(text.strip())
    if not match:
        return None
    card = project / code_checks.CONTEXT_FILE
    current = card.read_text(encoding="utf-8") if card.exists() else code_checks.context_skeleton(project)
    rules = [line for line in code_checks.section(current, SECTION).splitlines() if line.strip()]
    rule = f"- {' '.join(match.group(1).split())}"
    if rule not in rules:
        rules.append(rule)
    card.write_text(code_checks.set_section(current, SECTION, "\n".join(rules)), encoding="utf-8")
    return f"Regla apuntada en {code_checks.CONTEXT_FILE} del proyecto: {rule[2:]}. Chati la aplicará en cada encargo."
