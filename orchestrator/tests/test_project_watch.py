import sys
import time
from unittest.mock import patch

from coding import checkpoints, code_checks, project_watch


def test_warns_only_when_tests_that_passed_start_failing(tmp_path):
    project = tmp_path / "calc"
    project.mkdir()
    (project / "calc.py").write_text("def suma(a, b):\n    return a + b\n", encoding="utf-8")
    (project / "test_calc.py").write_text("from calc import suma\n\ndef test_suma():\n    assert suma(1, 2) == 3\n",
                                          encoding="utf-8")
    sessions = {"ses_1": [{"carpeta": str(project), "hora": time.time(), "commit": "x", "encargo": "y"}],
                "ses_vieja": [{"carpeta": str(tmp_path), "hora": 0, "commit": "x", "encargo": "y"}]}
    with patch.object(checkpoints, "_load", return_value=sessions), \
         patch.object(project_watch.task_owners, "owner", return_value="u1"), \
         patch.object(code_checks, "_python_for", return_value=sys.executable), \
         patch.object(project_watch, "STATE_FILE", tmp_path / "estado.json"):
        assert project_watch.recent_projects() == {project: "u1"}
        assert project_watch.check_all() == []
        (project / "calc.py").write_text("def suma(a, b):\n    return a - b\n", encoding="utf-8")
        warnings = project_watch.check_all()
        assert warnings == [("u1", "calc: han dejado de pasar los tests (test_suma)")]
        assert project_watch.check_all() == []
