import time
from pathlib import Path
from unittest.mock import patch

import main
from coding import agent_guard, agent_watch, checkpoints


def _old_file(path: Path, text: str = "x") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def test_existing_data_file_not_asked_for_is_blocked(tmp_path):
    csv = _old_file(tmp_path / "facturas" / "facturas.csv")
    started = time.time() + 1
    task = ["el programa calcular_total.py de la carpeta pruebas/facturas me da error. arreglalo"]
    assert agent_guard.blocked_data_edit(csv, task, started)
    assert not agent_guard.blocked_data_edit(csv, ["corrige facturas.csv, tiene una fila mal"], started)
    assert not agent_guard.blocked_data_edit(csv, ["el csv tiene los importes mal, arreglalo"], started)
    assert not agent_guard.blocked_data_edit(_old_file(tmp_path / "calcular_total.py"), task, started)
    assert not agent_guard.blocked_data_edit(tmp_path / "nuevo.csv", task, started)
    assert not agent_guard.blocked_data_edit(csv, task, time.time() - 60)
    assert not agent_guard.blocked_data_edit(_old_file(tmp_path / "requirements.txt"), task, started)


def test_edited_file_resolves_relative_paths_and_ignores_other_permissions(tmp_path):
    perm = {"permission": "edit", "patterns": ["datos/a.csv"], "filepath": ""}
    assert agent_guard.edited_file(perm, str(tmp_path)) == tmp_path / "datos" / "a.csv"
    assert agent_guard.edited_file({**perm, "filepath": str(tmp_path / "b.csv")}, None) == tmp_path / "b.csv"
    assert agent_guard.edited_file({"permission": "bash", "patterns": ["rm a.csv"]}, str(tmp_path)) is None


def test_chati_messages_do_not_count_as_user_requests():
    view = {"task": "arregla el programa", "steps": [
        {"kind": "user", "text": agent_guard.rejection_message(Path("C:/x/a.csv"))},
        {"kind": "user", "text": "y que no tarde tanto"}, {"kind": "text", "text": "a.csv"}]}
    assert agent_guard.user_requests(view) == ["arregla el programa", "y que no tarde tanto"]


def test_copy_folder_skips_whole_desktop_or_home(tmp_path):
    assert agent_guard.copy_folder(tmp_path / "a.py") == tmp_path.resolve()
    assert agent_guard.copy_folder(Path.home() / "Desktop" / "a.py") is None
    assert agent_guard.copy_folder(Path.home() / "a.py") is None


def _tool(tool, detail, **kw):
    return {"kind": "tool", "tool": tool, "status": "completed", "detail": detail, **kw}


def test_unproven_change_needs_a_good_run_after_the_last_edit():
    edit = _tool("edit", "C:/p/calcular_total.py")
    assert agent_guard.unproven_change([_tool("read", "C:/p/a.csv"), edit]) == "C:/p/calcular_total.py"
    assert agent_guard.unproven_change([edit, _tool("bash", "Get-Content calcular_total.py", exit=0)])
    assert agent_guard.unproven_change([edit, _tool("bash", "python calcular_total.py", exit=0)]) is None
    assert agent_guard.unproven_change([edit, _tool("bash", "python calcular_total.py", exit=1)])
    assert agent_guard.unproven_change([edit, _tool("chati_probar_programa", "C:/p/x.py", output="BIEN: ...")]) is None
    assert agent_guard.unproven_change([edit, _tool("chati_probar_programa", "C:/p/x.py", output="MAL: falla")])
    good = _tool("bash", "py calcular_total.py", exit=0)
    assert agent_guard.unproven_change([edit, good, edit]) and agent_guard.unproven_change([edit, good]) is None
    assert agent_guard.unproven_change([_tool("write", "C:/p/README.md")]) is None


def test_stuck_loop_spots_the_same_call_or_the_same_error_three_times():
    run = _tool("bash", "python notas.py", exit=1)
    assert agent_guard.stuck_loop([run, run]) is None
    assert "python notas.py" in agent_guard.stuck_loop([_tool("read", "a.py"), run, run, run])
    errs = [_tool("bash", f"pip install x{i}", status="error", error="ERROR: No matching distribution") for i in range(3)]
    assert "No matching distribution" in agent_guard.stuck_loop(errs)
    assert agent_guard.stuck_loop([run, _tool("edit", "notas.py"), run]) is None


def test_guard_rejects_the_edit_tells_the_agent_and_copies_before_other_changes(tmp_path):
    csv = _old_file(tmp_path / "facturas.csv")
    view = {"task": "calcular_total.py da error, arreglalo", "steps": [], "directory": str(tmp_path),
            "permissions": [{"id": "per_1", "permission": "edit", "patterns": ["facturas.csv"], "filepath": str(csv)}]}
    with patch.object(main.opencode_client, "reply_permission") as reply, \
         patch.object(main.opencode_client, "continue_task") as cont, \
         patch.object(checkpoints, "snapshot") as snap:
        assert agent_watch._guard_permissions("http://x", "ses_1", view, time.time() + 1, set())
        reply.assert_called_once_with("http://x", "per_1", "reject")
        assert "facturas.csv" in cont.call_args.args[2] and not snap.called

        view["permissions"] = [{"id": "per_2", "permission": "edit", "patterns": ["calcular_total.py"],
                                "filepath": ""}]
        copied = set()
        assert not agent_watch._guard_permissions("http://x", "ses_1", view, time.time() + 1, copied)
        assert not agent_watch._guard_permissions("http://x", "ses_1", view, time.time() + 1, copied)
        snap.assert_called_once_with("ses_1", tmp_path.resolve(), view["task"])
        assert reply.call_count == 1


def test_evidence_names_the_run_that_proves_the_last_change():
    edit = _tool("edit", "C:/p/calcular_total.py")
    run = _tool("bash", "python calcular_total.py", exit=0, output="\nTotal facturado: 1312.49 EUR\n")
    assert agent_guard.evidence([edit, run]) == \
        "✓ Comprobado: python calcular_total.py → Total facturado: 1312.49 EUR"
    probe = _tool("chati_probar_programa", "C:/p/contador.py", output="BIEN: se abre una ventana ('Contador')\n"
                  "Lo que ha escrito:\n(no ha escrito nada)\n(Ya lo he cerrado.)")
    assert agent_guard.evidence([edit, probe]).startswith("✓ Comprobado: probar_programa C:/p/contador.py → BIEN")
    console = _tool("chati_probar_programa", "C:/p/total.py", output="BIEN: ha terminado sin errores (codigo 0).\n"
                    "Lo que ha escrito:\nTotal facturado: 1312.49 EUR\n(Ya lo he cerrado.)")
    assert agent_guard.evidence([edit, console]).endswith("→ Total facturado: 1312.49 EUR")
    assert agent_guard.evidence([run, edit]) == ""


def test_final_report_says_what_was_proven_and_what_was_not():
    edit_a, edit_b = _tool("edit", "C:/p/precios.py"), _tool("write", "C:/p/informe.py")
    data = _tool("edit", "C:/p/notas.md")
    run_a = _tool("bash", "python precios.py", exit=0, output="Total: 10\n")
    text = agent_guard.report([edit_a, edit_b, data, run_a])
    assert "Probado después de cambiarlo: precios.py" in text and "✗ Sin comprobar: informe.py" in text
    assert "Otros archivos cambiados: notas.md" in text and "Total: 10" in text
    assert "✗ Sin comprobar: precios.py" in agent_guard.report([edit_a, run_a, edit_a])
    tests = _tool("bash", "python -m pytest -q", exit=0, output="2 passed")
    assert "Sin comprobar" not in agent_guard.report([edit_a, edit_b, tests])
    assert agent_guard.report([run_a]) == ""


def test_bulk_delete_or_move_shows_the_exact_files_affected(tmp_path):
    for name in ("a.log", "b.log", "notas.txt"):
        (tmp_path / name).write_text("x", encoding="utf-8")
    assert agent_guard.affected_files(f'Remove-Item "{tmp_path.as_posix()}/*.log"', None) == ["a.log", "b.log"]
    assert agent_guard.affected_files("Move-Item -Path *.log -Destination antiguos/", str(tmp_path)) == \
        ["a.log", "b.log"]
    assert agent_guard.affected_files("Remove-Item *.pdf", str(tmp_path)) == []
    assert agent_guard.affected_files("Remove-Item notas.txt", str(tmp_path)) is None
    assert agent_guard.affected_files("Get-ChildItem *.log", str(tmp_path)) is None


def test_a_chati_message_left_unanswered_is_detected():
    edit = _tool("edit", "C:/p/total.py", status="error")
    ours = {"kind": "user", "text": agent_guard.rejection_message(Path("C:/p/datos.csv"))}
    assert agent_guard.unanswered_chati_message([edit, ours])
    assert not agent_guard.unanswered_chati_message([edit, ours, {"kind": "text", "text": "Vale, arreglo el codigo"}])
    assert not agent_guard.unanswered_chati_message([{"kind": "user", "text": "y que no tarde"}])


def test_teach_mode_only_when_asked_and_not_counted_as_a_user_request():
    note = agent_guard.teach_note("arregla el csv y enséñame por qué fallaba")
    assert "quiere aprender" in note and agent_guard.teach_note("arregla el csv") == ""
    view = {"task": "arregla total.py, explícame por qué" + note, "steps": []}
    assert agent_guard.user_requests(view) == ["arregla total.py, explícame por qué"]


def test_programs_left_open_are_stopped_unless_the_user_asked_to_keep_them():
    assert agent_guard.keeps_running(["arranca mi web de pruebas/tienda"])
    assert agent_guard.keeps_running(["arreglalo y déjalo abierto"])
    assert not agent_guard.keeps_running(["la web de pruebas/tienda da error 500, arreglala"])


def test_stop_started_since_only_kills_what_the_agent_started_during_the_task(tmp_path):
    import json as _json
    import subprocess
    import sys

    from coding import agent_tools
    proc = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
    try:
        now = time.time()
        with patch.object(agent_tools, "STARTED_FILE", tmp_path / "a.json"):
            agent_tools.STARTED_FILE.write_text(_json.dumps([
                {"pid": proc.pid, "comando": "python servidor.py", "cuando": now},
                {"pid": proc.pid, "comando": "de una tarea anterior", "cuando": now - 3600}]), encoding="utf-8")
            assert agent_tools.stop_started_since(now - 5) == ["python servidor.py"]
        proc.wait(timeout=10)
    finally:
        proc.kill()


def test_existing_tests_are_protected_unless_asked(tmp_path):
    test = _old_file(tmp_path / "tests" / "test_precios.py")
    other = _old_file(tmp_path / "test_api.py")
    started = time.time() + 1
    assert agent_guard.blocked_test_edit(test, ["el descuento sale mal, arreglalo"], started)
    assert agent_guard.blocked_test_edit(other, ["los tests fallan, arreglalo sin cambiar los tests"], started)
    assert not agent_guard.blocked_test_edit(test, ["añade un test para el descuento cero"], started)
    assert not agent_guard.blocked_test_edit(_old_file(tmp_path / "precios.py"), ["arreglalo"], started)
    assert not agent_guard.blocked_test_edit(tmp_path / "tests" / "test_nuevo.py", ["arreglalo"], started)


def test_standing_corrections_are_kept_and_one_off_ones_are_not():
    assert agent_guard.standing_correction("No, nunca uses tkinter: prefiero consola") == \
        "No, nunca uses tkinter: prefiero consola"
    assert agent_guard.standing_correction("a partir de ahora los informes en Excel")
    assert agent_guard.standing_correction("no, ponlo en la carpeta Trabajo") is None
    assert agent_guard.standing_correction("siempre") is None


def test_pip_install_into_the_system_python_is_rejected():
    bash = lambda cmd: {"permission": "bash", "patterns": [cmd]}
    fix = ["informe.py dice que falta tabulate. arreglalo"]
    assert agent_guard.global_pip_install(bash("pip install tabulate"), fix)
    assert agent_guard.global_pip_install(bash("python -m pip install tabulate"), fix)
    assert agent_guard.global_pip_install(bash("py -3.12 -m pip install tabulate"), fix)
    assert not agent_guard.global_pip_install(bash(".venv/Scripts/python.exe -m pip install tabulate"), fix)
    assert not agent_guard.global_pip_install(bash("pip list"), fix)
    assert not agent_guard.global_pip_install(bash("pip install tabulate"), ["instala tabulate en el sistema"])
