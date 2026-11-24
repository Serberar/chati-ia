from unittest.mock import patch

from coding import agent_guard, agent_watch, lessons


def _run(cmd, exit_code, output=""):
    return {"kind": "tool", "tool": "bash", "status": "completed", "detail": cmd, "exit": exit_code, "output": output}


def test_only_a_failure_that_was_then_fixed_is_worth_a_lesson():
    fail = _run("python total.py", 1, "ValueError: could not convert string to float: '1.200,00'")
    good = _run("python total.py", 0, "Total: 1312.49")
    assert "could not convert" in lessons.failed_then_fixed([fail, good])
    assert lessons.failed_then_fixed([good]) is None
    assert lessons.failed_then_fixed([good, fail]) is None
    probe = {"kind": "tool", "tool": "chati_probar_programa", "status": "completed", "detail": "x.py"}
    assert lessons.failed_then_fixed([{**probe, "output": "MAL: falla"}, {**probe, "output": "BIEN: ventana"}])


def test_lessons_are_saved_and_found_for_similar_tasks(tmp_path):
    with patch.object(lessons, "LESSONS_FILE", tmp_path / "l.json"):
        assert lessons.note("el csv de facturas da ValueError al sumar importes") == ""
        lesson = lessons.clean("- Importes con coma decimal y punto de miles dan ValueError: quitar puntos y "
                               "cambiar la coma por punto antes de float().\nmas texto")
        lessons.add(lesson, "calcular_total.py de facturas da error al sumar importes")
        lessons.add(lesson, "otra vez")
        assert lessons.relevant("el script de facturas falla al sumar los importes") == [lesson]
        assert lessons.relevant("haz una ventana con un boton") == []
        assert lessons.clean("NADA") is None
        assert "Lecciones de tareas anteriores" in lessons.note("sumar importes de facturas")


def test_chati_notes_in_the_task_do_not_count_as_asking_for_a_file():
    view = {"task": "arregla calcular_total.py" + lessons.note("") + "\n\n[Lecciones de tareas anteriores]\n- el csv",
            "steps": []}
    assert agent_guard.user_requests(view) == ["arregla calcular_total.py"]


def test_long_tasks_that_went_well_first_time_give_a_procedure_and_main_learns_it(tmp_path):
    ok = [_run(f"python paso{i}.py", 0) for i in range(6)]
    assert lessons.skill_worthy(ok) and not lessons.skill_worthy(ok[:3])
    assert not lessons.skill_worthy([_run("python a.py", 1)] + ok)
    import main
    view = {"task": "empaqueta la app de ventas como exe\n\n[Nota de Chati] x", "steps": ok}
    with patch.object(lessons, "LESSONS_FILE", tmp_path / "l.json"), \
         patch.object(main.ollama, "chat", return_value="Para empaquetar una app tkinter: 1) probarla 2) compilar_exe"):
        agent_watch._learn(view)
        assert lessons._load()[0] == {"leccion": "Para empaquetar una app tkinter: 1) probarla 2) compilar_exe",
                                      "tarea": "empaqueta la app de ventas como exe",
                                      "cuando": lessons._load()[0]["cuando"]}
