import sys
from unittest.mock import patch

import main
from coding import agent_watch, checkpoints, code_checks

TEST = "from calc import suma, resta\n\ndef test_suma():\n    assert suma(1, 2) == 3\n\n" \
       "def test_resta():\n    assert resta(5, 3) == 2\n"


def test_failures_from_before_the_task_are_told_apart(tmp_path):
    project = tmp_path / "proyecto"
    project.mkdir()
    (project / "calc.py").write_text("def suma(a, b):\n    return a + b\n\ndef resta(a, b):\n    return a + b\n",
                                     encoding="utf-8")
    (project / "test_calc.py").write_text(TEST, encoding="utf-8")
    with patch.object(checkpoints, "COPIES_DIR", tmp_path / "copias"), \
         patch.object(checkpoints, "SESSIONS_FILE", tmp_path / "copias" / "s.json"), \
         patch.object(code_checks, "_python_for", return_value=sys.executable):
        checkpoints.snapshot("ses_b", project, "arregla suma")
        (project / "calc.py").write_text("def suma(a, b):\n    return b + a\n\ndef resta(a, b):\n    return a + b\n",
                                         encoding="utf-8")
        ok, output = code_checks.run_tests(project)
        assert not ok and code_checks.failing_tests(output) == {"test_calc.py::test_resta"}
        assert agent_watch._baseline_failures("ses_b", project) == {"test_calc.py::test_resta"}


def _watch(folder, test_results, baseline, undo_left=1):
    idle = {"permissions": [], "questions": [], "status": "idle", "error": None, "steps": []}
    results = iter(test_results)
    sent = []
    info = {"estado": "", "final": ""}
    states = iter([{}] + [{"a": i} for i in range(1, 10)])
    with patch.object(main.time, "sleep"), \
         patch.object(code_checks, "folder_state", side_effect=lambda f: next(states)), \
         patch.object(main.opencode_client, "busy_session_ids", return_value=[]), \
         patch.object(main.opencode_client, "get_task_view", return_value=idle), \
         patch.object(code_checks, "run_tests", side_effect=lambda f: next(results)), \
         patch.object(code_checks, "run_lint", return_value=None), \
         patch.object(checkpoints, "diff_since_last", return_value=""), \
         patch.object(checkpoints, "available", return_value=undo_left), \
         patch.object(agent_watch, "_baseline_failures", return_value=baseline) as base, \
         patch.object(agent_watch, "_update_context_file", return_value=True), \
         patch.object(main.opencode_client, "continue_task", side_effect=lambda *a: sent.append(a[2])):
        agent_watch._watch_code_task("ses_b", folder, False, info)
    return info["estado"], sent, base.call_count


def test_watch_does_not_blame_the_agent_for_tests_that_already_failed(tmp_path):
    estado, sent, calls = _watch(tmp_path, [(False, "FAILED test_calc.py::test_resta - assert 8 == 2")],
                                 {"test_calc.py::test_resta"})
    assert sent == [] and calls == 1
    assert estado.startswith("✓ El encargo no ha roto nada") and "test_resta" in estado


def test_watch_offers_undo_when_the_task_broke_tests_that_passed(tmp_path):
    out = "FAILED test_calc.py::test_resta - x\nFAILED test_calc.py::test_suma - y"
    estado, sent, calls = _watch(tmp_path, [(False, out)] * 3, {"test_calc.py::test_resta"})
    assert calls == 1 and len(sent) == agent_watch.CODE_TEST_RETRIES
    assert "ya fallaban antes del encargo" in sent[0] and "test_calc.py::test_resta" in sent[0]
    assert "ha roto 1 test(s)" in estado and "test_suma" in estado and "Deshacer" in estado
