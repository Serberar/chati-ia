"""Vigilancia de las tareas del agente y del modo codigo: permisos, pruebas, revision, aprendizaje y trayectorias."""
import threading
import time
from pathlib import Path

from coding import (
    agent_guard,
    agent_tools,
    checkpoints,
    code_checks,
    lessons,
    opencode_client,
    project_git,
    project_rules,
    reviewer,
    trajectories,
)
from infra.core import CONFIG, log, ollama

PROJECT_MAP_CHARS = 3000


def project_map_note(project: Path) -> str:
    text = agent_tools.project_map(str(project))
    if text.startswith(("No existe", "No hay archivos")):
        return ""
    if len(text) > PROJECT_MAP_CHARS:
        text = text[:PROJECT_MAP_CHARS] + "\n[... mas: chati_mapa_proyecto de una subcarpeta ...]"
    return ("\n\n[Nota de Chati] Mapa del proyecto (archivos, clases y funciones): usalo para saber que leer; lee solo "
            f"los trozos que necesites.\n{text}")


def code_facts(task: str, project: Path) -> str:
    notes = []
    for name, eco in code_checks.package_mentions(task):
        notes.append(agent_tools.package_info(name, eco).splitlines()[0])
    if notes:
        notes.insert(0, "Datos comprobados por Chati en el registro de paquetes (fiate de esto, no de lo que "
                        "recuerdes; si dice NO EXISTE, dilo claramente y propone una alternativa real):")
    rename = code_checks.rename_request(task)
    if rename and "NO se ha cambiado" in agent_tools.find_symbol(str(project), rename[0]):
        notes.append(f"Para este cambio de nombre usa UNA llamada: chati_renombrar con carpeta=\"{project}\", "
                     f"viejo=\"{rename[0]}\", nuevo=\"{rename[1]}\". Lo cambia en todos los archivos a la vez. No uses "
                     "bash ni edites archivo por archivo. Despues pasa los tests.")
    what = code_checks.remember_request(task)
    if what:
        saved = agent_tools.memory_save(what[:60], what, "proyecto", project.name)
        log.info("Modo Codigo: %s", saved)
        notes.append(f"Chati ya lo ha guardado en tu memoria ({saved}). Confirmalo en una linea; no hace falta "
                     "que lo guardes otra vez ni que toques archivos.")
    return ("\n\n[Nota de Chati]\n" + "\n".join(notes)) if notes else ""


CODE_TEST_RETRIES = 2
task_branches: dict[str, tuple[str, str]] = {}
CODE_WATCH_HOURS = 3
code_watch: dict[str, dict] = {}
code_watch_running: set[str] = set()


def _auto_approve(base: str, session_id: str, started: float) -> None:
    view = opencode_client.get_task_view(base, session_id)
    if _guard_permissions(base, session_id, view, started):
        return
    for perm in view["permissions"]:
        if code_checks.auto_approvable(perm["permission"], perm["patterns"]):
            log.info("Modo Codigo sin preguntar: concedido %s %s", perm["permission"], perm["patterns"][:2])
            opencode_client.reply_permission(base, perm["id"], "once")


def _guard_permissions(base: str, session_id: str, view: dict, started: float,
                       copied: set[Path] | None = None) -> bool:
    requests_ = agent_guard.user_requests(view)
    for perm in view["permissions"]:
        if agent_guard.global_pip_install(perm, requests_):
            log.warning("Guardia: rechazado pip install en el Python del sistema: %s", perm.get("patterns"))
            opencode_client.reply_permission(base, perm["id"], "reject")
            opencode_client.continue_task(base, session_id, agent_guard.global_pip_message())
            return True
        path = agent_guard.edited_file(perm, view.get("directory"))
        if agent_guard.blocked_data_edit(path, requests_, started):
            log.warning("Guardia de datos: rechazado que el agente cambie %s", path)
            opencode_client.reply_permission(base, perm["id"], "reject")
            opencode_client.continue_task(base, session_id, agent_guard.rejection_message(path))
            return True
        if agent_guard.blocked_test_edit(path, requests_, started):
            log.warning("Tests protegidos: rechazado que el agente cambie %s", path)
            opencode_client.reply_permission(base, perm["id"], "reject")
            opencode_client.continue_task(base, session_id, agent_guard.protected_test_message(path))
            return True
        rule = project_rules.forbidden(path)
        if rule:
            log.warning("Reglas del proyecto: rechazado que el agente cambie %s (%s)", path, rule)
            opencode_client.reply_permission(base, perm["id"], "reject")
            opencode_client.continue_task(base, session_id, f"[Chati] No puedes cambiar {path.name}: las reglas del "
                                                            f"proyecto dicen \"no tocar: {rule}\". Hazlo sin tocarlo "
                                                            "o, si es imprescindible, explicale al usuario por que.")
            return True
        folder = agent_guard.copy_folder(path) if path is not None and copied is not None else None
        if folder and folder not in copied:
            copied.add(folder)
            checkpoints.snapshot(session_id, folder, view.get("task") or "")
    return False


AGENT_GUARD_SECONDS = 2
AGENT_WATCH_HOURS = 3
agent_watch_running: set[str] = set()
_agent_started: dict[str, float] = {}
_agent_copied: dict[str, set[Path]] = {}
agent_allowed: dict[str, set[Path]] = {}
estimates: dict[str, str] = {}
STALL_SECONDS = 600
STALL_RETRIES = 2
stalled: dict[str, float] = {}


def _approve_allowed_folders(base: str, session_id: str, view: dict) -> None:
    allowed = agent_allowed.get(session_id)
    if not allowed:
        return
    for perm in view["permissions"]:
        path = agent_guard.edited_file(perm, view.get("directory"))
        try:
            inside = path is not None and any(path.resolve().is_relative_to(folder) for folder in allowed)
        except OSError:
            inside = False
        if inside:
            log.info("Modo Agente: concedido %s (carpeta permitida)", path)
            opencode_client.reply_permission(base, perm["id"], "once")


def resume_agent_watches() -> None:
    time.sleep(20)
    base = CONFIG["opencode"]["base_url"]
    for sid in set(opencode_client.busy_session_ids(base)) | set(opencode_client.waiting_sessions(base)):
        log.info("Modo Agente: vuelvo a vigilar la tarea %s tras el reinicio", sid)
        start_agent_watch(sid)


def _save_trajectory(session_id: str, mode: str, started: float, verification: str) -> None:
    try:
        view = opencode_client.get_task_view(CONFIG["opencode"]["base_url"], session_id)
    except Exception as exc:
        log.warning("No se pudo leer la tarea %s al acabar: %s", session_id, exc)
        return
    if not agent_guard.keeps_running(agent_guard.user_requests(view)):
        stopped = agent_tools.stop_started_since(started)
        if stopped:
            log.info("Al acabar %s: parados los programas que dejo abiertos: %s", session_id, stopped)
    try:
        trajectories.save(view, mode, started, verification)
    except Exception as exc:
        log.warning("No se pudo guardar la trayectoria de %s: %s", session_id, exc)


def start_agent_watch(session_id: str | None) -> None:
    if not session_id or session_id in agent_watch_running:
        return
    agent_watch_running.add(session_id)
    started = _agent_started.setdefault(session_id, time.time())
    copied = _agent_copied.setdefault(session_id, set())

    def run():
        try:
            _watch_agent_task(session_id, started, copied)
        finally:
            agent_watch_running.discard(session_id)
            _save_trajectory(session_id, "agente", started, agent_verification.get(session_id, ""))

    threading.Thread(target=run, daemon=True).start()


def _learn(view: dict) -> str | None:
    steps = view.get("steps", [])
    error = lessons.failed_then_fixed(steps)
    if not error and not lessons.skill_worthy(steps):
        return None
    texts = [s.get("text", "") for s in steps if s.get("kind") == "text"]
    summary = texts[-1] if texts else ""
    task = (view.get("task") or "").split("\n\n[")[0]
    messages = lessons.extraction_messages(task, error, summary) if error else \
        lessons.skill_messages(task, steps, summary)
    try:
        reply = ollama.chat(CONFIG["opencode"]["model_potente"], messages, temperature=0.1)
    except Exception as exc:
        log.warning("No se pudo sacar la leccion de la tarea: %s", exc)
        return None
    lesson = lessons.clean(reply)
    if lesson:
        lessons.add(lesson, task)
        log.info("Leccion aprendida: %s", lesson)
    return lesson


def _review(session_id: str, view: dict, proof: str) -> list[str]:
    diff = checkpoints.diff_since_last(session_id, max_chars=8000)
    if not diff:
        return []
    requests_ = agent_guard.user_requests(view)
    problems = reviewer.overreach(diff, requests_)
    if problems:
        return problems
    texts = [s.get("text", "") for s in view.get("steps", []) if s.get("kind") == "text"]
    try:
        reply = ollama.chat(CONFIG["opencode"]["model_potente"],
                            reviewer.review_messages("\n".join(requests_), diff, proof, texts[-1] if texts else ""),
                            temperature=0.1)
    except Exception as exc:
        log.warning("No se pudo revisar la tarea %s: %s", session_id, exc)
        return []
    motivo = reviewer.parse(reply)
    return [motivo] if motivo else []


AGENT_PROOF_NUDGES = 2
AGENT_WAKES = 2
agent_verification: dict[str, str] = {}


def _watch_agent_task(session_id: str, started: float, copied: set[Path]) -> None:
    base = CONFIG["opencode"]["base_url"]
    deadline = time.time() + AGENT_WATCH_HOURS * 3600
    idle_since = None
    nudges = 0
    reviewed = False
    wakes = 0
    loops_seen = 0
    agent_verification.pop(session_id, None)
    while time.time() < deadline:
        time.sleep(AGENT_GUARD_SECONDS)
        try:
            view = opencode_client.get_task_view(base, session_id)
            if _guard_permissions(base, session_id, view, started, copied):
                idle_since = None
                continue
            _approve_allowed_folders(base, session_id, view)
            steps = view.get("steps", [])
            loop = agent_guard.stuck_loop(steps) if len(steps) >= loops_seen + agent_guard.LOOP_REPEATS else None
            if loop and view["status"] != "idle":
                loops_seen = len(steps)
                log.info("Modo Agente: bucle en %s: %s", session_id, loop)
                opencode_client.continue_task(base, session_id, agent_guard.loop_message(loop))
        except Exception:
            continue
        if view["status"] != "idle" or view["permissions"] or view["questions"]:
            idle_since = None
            continue
        idle_since = idle_since or time.time()
        if time.time() - idle_since <= 30:
            continue
        if agent_guard.unanswered_chati_message(view.get("steps", [])) and wakes < AGENT_WAKES:
            wakes += 1
            log.info("Modo Agente: %s se ha parado sin leer el mensaje de Chati, se le despierta (%d)", session_id, wakes)
            opencode_client.continue_task(base, session_id, agent_guard.wake_up_message())
            idle_since = None
            continue
        unproven = None if view.get("error") else agent_guard.unproven_change(view.get("steps", []))
        if not unproven:
            proof = agent_guard.evidence(view.get("steps", []))
            if not view.get("error") and not reviewed:
                reviewed = True
                agent_verification[session_id] = "Revisando el trabajo antes de darlo por bueno…"
                problems = _review(session_id, view, proof)
                if problems:
                    log.info("Modo Agente: el revisor devuelve %s: %s", session_id, problems)
                    agent_verification[session_id] = "La revisión ha encontrado algo: se lo devuelvo…"
                    opencode_client.continue_task(base, session_id, reviewer.review_request(problems))
                    idle_since = None
                    continue
            agent_verification.pop(session_id, None)
            summary = agent_guard.report(view.get("steps", []))
            if summary or proof or nudges:
                agent_verification[session_id] = summary or proof or "✓ Lo ha probado después de cambiarlo."
            if not view.get("error"):
                _learn(view)
            return
        if nudges >= AGENT_PROOF_NUDGES:
            agent_verification[session_id] = (f"✗ Ha cambiado {Path(unproven).name} y no ha conseguido probarlo: "
                                               "compruébalo tú antes de fiarte. Te deja una consulta para otra IA.")
            opencode_client.continue_task(base, session_id, agent_guard.consult_request())
            return
        nudges += 1
        log.info("Modo Agente: %s cambiado sin probar, se le pide probarlo (%d)", unproven, nudges)
        agent_verification[session_id] = f"Ha cambiado {Path(unproven).name} sin probarlo: se lo pido…"
        opencode_client.continue_task(base, session_id, agent_guard.proof_request(unproven, nudges,
                                                                                  AGENT_PROOF_NUDGES))
        idle_since = None


def _update_context_file(session_id: str, folder: Path, summary: str,
                         notes: tuple[str | None, str, list[dict]] | None = None) -> bool:
    path = folder / code_checks.CONTEXT_FILE
    current = text = None
    try:
        current = path.read_text(encoding="utf-8") if path.exists() else code_checks.context_skeleton(folder)
        diff = checkpoints.diff_since_last(session_id, max_chars=8000, exclude=(code_checks.CONTEXT_FILE,))
        reply = ollama.chat(CONFIG["opencode"]["model_potente"],
                            code_checks.context_update_messages(current, diff, summary), temperature=0.1)
        text = code_checks.clean_context(reply, current)
        if not text:
            log.warning("Ficha de %s descartada: el modelo no devolvio una ficha valida", folder)
    except Exception as exc:
        log.warning("No se pudo actualizar %s en %s: %s", code_checks.CONTEXT_FILE, folder, exc)
    if current is None or (text is None and notes is None):
        return False
    final = text or current
    if notes:
        lesson, task, todos = notes
        final = code_checks.project_notes(final, current, lesson, task, summary, todos)
    path.write_text(final, encoding="utf-8")
    return text is not None


def _baseline_failures(session_id: str, folder: Path) -> set[str]:
    import tempfile
    with tempfile.TemporaryDirectory(prefix="chati_antes_") as tmp:
        try:
            if not checkpoints.export_first(session_id, Path(tmp)):
                return set()
            return code_checks.baseline_failures(folder, Path(tmp)) or set()
        except Exception as exc:
            log.warning("No se pudo sacar la linea base de tests de %s: %s", folder, exc)
            return set()


def start_code_watch(session_id: str, folder: Path, big: bool, autonomous: bool = False,
                      only_look: bool = False) -> None:
    info = {"estado": "Planificando antes de construir…" if big else "", "final": "",
            "autonomo": autonomous or (code_watch.get(session_id) or {}).get("autonomo", False),
            "solo_mirar": only_look, "pausa_hasta": 0}
    code_watch[session_id] = info
    code_watch_running.add(session_id)

    def run():
        try:
            _watch_code_task(session_id, folder, big, info)
        finally:
            code_watch_running.discard(session_id)
            if not only_look:
                _save_trajectory(session_id, "codigo", _agent_started.get(session_id, time.time()),
                                 info.get("estado", ""))

    threading.Thread(target=run, daemon=True).start()


def _watch_code_task(session_id: str, folder: Path, big: bool, info: dict) -> None:
    base = CONFIG["opencode"]["base_url"]
    before = code_checks.folder_state(folder)
    started = _agent_started.setdefault(session_id, time.time())
    phase = "plan" if big else "build"
    attempts = 0
    deadline = time.time() + CODE_WATCH_HOURS * 3600
    autonomous = info.get("autonomo", False)
    nudges = 0
    reviewed = ruled = asked_test = False
    baseline: set[str] | None = None
    time.sleep(3 if autonomous else 20)
    while time.time() < deadline:
        time.sleep(3 if autonomous else 10)
        if time.time() < info.get("pausa_hasta", 0):
            continue
        try:
            if autonomous:
                _auto_approve(base, session_id, started)
            if session_id in opencode_client.busy_session_ids(base):
                continue
            view = opencode_client.get_task_view(base, session_id)
            if _guard_permissions(base, session_id, view, started):
                continue
        except Exception:
            continue
        if view["permissions"] or view["questions"] or view["status"] != "idle":
            continue
        if view.get("error"):
            info["estado"] = ""
            return
        steps = view.get("steps", [])
        unanswered = agent_guard.unanswered_chati_message(steps)
        undecided = code_checks.lists_without_recommending(steps) and phase != "plan"
        stuck = code_checks.broken_tool_call(steps) or code_checks.ended_without_answer(steps) or unanswered \
            or undecided
        if stuck and nudges < code_checks.TOOL_CALL_NUDGES:
            nudges += 1
            broken = code_checks.broken_tool_call(steps)
            log.info("Modo Codigo: %s, se le pide seguir (%d)",
                     "llamada a herramienta escrita como texto" if broken else
                     "opciones sin recomendar" if undecided else "acabo sin contestar", nudges)
            agent = "agent_code_plan" if info.get("solo_mirar") or phase == "plan" else "agent_code"
            message = code_checks.tool_call_nudge() if broken else \
                agent_guard.wake_up_message() if unanswered else \
                code_checks.recommend_nudge() if undecided else code_checks.answer_nudge()
            opencode_client.continue_task(base, session_id, message, CONFIG["opencode"][agent])
            time.sleep(20)
            continue
        if info.get("solo_mirar"):
            return
        if info.pop("construir", False):
            phase = "build"
        if phase == "plan" and not autonomous:
            info["estado"] = "📝 Plan listo. Si te parece bien, di «adelante»; si no, dime qué cambiar."
            return
        if phase == "plan":
            phase = "build"
            info["estado"] = "Plan hecho: construyendolo paso a paso…"
            opencode_client.continue_task(
                base, session_id, "[Chati] Adelante: haz ese plan paso a paso, marcando cada paso con todowrite, y "
                                  "comprueba con los tests al final.", CONFIG["opencode"]["agent_code"])
            time.sleep(20)
            continue
        changed = code_checks.changed_files(before, code_checks.folder_state(folder))
        if not changed:
            info["estado"] = ""
            return
        info["estado"] = "Comprobando con los tests…"
        result = code_checks.run_tests(folder)
        pre_existing: list[str] = []
        if result is not None and not result[0]:
            if baseline is None:
                info["estado"] = "Los tests fallan: miro si ya fallaban antes del encargo…"
                baseline = _baseline_failures(session_id, folder)
            now = code_checks.failing_tests(result[1])
            if baseline and now and now <= baseline:
                result, pre_existing = (True, result[1]), sorted(now)
        if result is None or result[0]:
            lint = code_checks.run_lint(folder, changed)
            if lint is not None and not lint[0]:
                attempts += 1
                if attempts > CODE_TEST_RETRIES:
                    info["estado"] = "✗ El analizador sigue encontrando errores despues de devolverselo al agente."
                    return
                info["estado"] = f"✗ El analizador encuentra errores: se lo devuelvo al agente ({attempts} de " \
                                 f"{CODE_TEST_RETRIES})…"
                opencode_client.continue_task(base, session_id,
                                              code_checks.lint_message(lint[1], attempts, CODE_TEST_RETRIES),
                                              CONFIG["opencode"]["agent_code"])
                time.sleep(20)
                continue
            if not asked_test and result is not None and not code_checks.touches_tests(changed) and \
                    code_checks.is_bug_fix(" ".join(agent_guard.user_requests(view))):
                asked_test = True
                info["estado"] = "Tests bien: le pido un test que demuestre el arreglo…"
                opencode_client.continue_task(base, session_id, code_checks.reproduce_request(),
                                              CONFIG["opencode"]["agent_code"])
                time.sleep(20)
                continue
            if not ruled:
                ruled = True
                problems = reviewer.overreach(
                    checkpoints.diff_since_last(session_id, max_chars=20000, exclude=(code_checks.CONTEXT_FILE,)),
                    agent_guard.user_requests(view))
                if problems:
                    log.info("Modo Codigo: el revisor devuelve %s: %s", session_id, problems)
                    info["estado"] = "La revisión ha encontrado algo: se lo devuelvo al agente…"
                    opencode_client.continue_task(base, session_id, reviewer.review_request(problems),
                                                  CONFIG["opencode"]["agent_code"])
                    time.sleep(20)
                    continue
            diff = "" if reviewed else checkpoints.diff_since_last(session_id, exclude=(code_checks.CONTEXT_FILE,))
            if diff and code_checks.needs_review(diff):
                reviewed = True
                info["estado"] = "Tests bien: el agente repasa sus propios cambios…"
                opencode_client.continue_task(base, session_id, code_checks.review_request(diff),
                                              CONFIG["opencode"]["agent_code"])
                time.sleep(20)
                continue
            final = ("✓ Chati ha ejecutado los tests y pasan." if result
                     else "Este proyecto no tiene tests: Chati no ha podido comprobar los cambios.")
            if pre_existing:
                final = (f"✓ El encargo no ha roto nada: fallan {len(pre_existing)} test(s) que ya fallaban antes "
                         f"({', '.join(t.split('::')[-1] for t in pre_existing[:5])}).")
            info["estado"] = final + " Actualizando la ficha del proyecto (AGENTS.md)…"
            texts = [s.get("text", "") for s in view.get("steps", []) if s.get("kind") == "text"]
            lesson = _learn(view)
            task = (view.get("task") or "").split("\n\n[")[0]
            updated = _update_context_file(session_id, folder, texts[-1] if texts else "",
                                           notes=(lesson, task, view.get("todos") or []))
            info["estado"] = final + (" Ficha del proyecto (AGENTS.md) actualizada." if updated else "")
            if session_id in task_branches:
                branch, task = task_branches[session_id]
                sha = project_git.commit(folder, branch, task)
                if sha:
                    info["estado"] += (f" Guardado en la rama {branch} (commit {sha}); para llevarlo a tu rama: "
                                       f"git merge {branch}. No se ha subido nada.")
            return
        _ok, output = result
        if baseline:
            output += ("\n\n[Chati] Estos ya fallaban antes del encargo (no hace falta que los arregles salvo que te "
                       "lo pidan): " + ", ".join(sorted(baseline)[:10]))
        attempts += 1
        if attempts > CODE_TEST_RETRIES:
            broken = sorted(code_checks.failing_tests(output) - (baseline or set()))
            info["estado"] = "✗ Los tests siguen fallando despues de devolverselo al agente: revisalo."
            if broken and baseline is not None and checkpoints.available(session_id):
                info["estado"] = (f"✗ El encargo ha roto {len(broken)} test(s) que antes pasaban "
                                  f"({', '.join(t.split('::')[-1] for t in broken[:5])}). Si no te convence, "
                                  "pulsa Deshacer y el proyecto vuelve a como estaba.")
            return
        info["estado"] = f"✗ Los tests fallan: se lo devuelvo al agente ({attempts} de {CODE_TEST_RETRIES})…"
        log.info("Modo Codigo: tests fallan en %s, se lo devuelvo al agente (%d)", folder, attempts)
        opencode_client.continue_task(base, session_id,
                                      code_checks.failure_message(output, attempts, CODE_TEST_RETRIES),
                                      CONFIG["opencode"]["agent_code"])
        time.sleep(20)
    info["estado"] = ""
