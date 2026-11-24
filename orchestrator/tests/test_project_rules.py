import json
import sys
from unittest.mock import patch

from coding import agent_feedback, agent_watch, code_checks, project_rules


def _project(tmp_path):
    (tmp_path / "config").mkdir()
    (tmp_path / "app").mkdir()
    (tmp_path / "AGENTS.md").write_text("# P\n## A\n## B\n## C\n## D\n", encoding="utf-8")
    return tmp_path


def test_rules_are_added_from_the_chat_and_forbid_files(tmp_path):
    project = _project(tmp_path)
    assert "apuntada" in project_rules.add_request("/regla no tocar: config/, secrets.json", project)
    project_rules.add_request("/regla no tocar: config/, secrets.json", project)
    assert project_rules.add_request("toca config", project) is None
    card = (project / "AGENTS.md").read_text(encoding="utf-8")
    assert card.count("- no tocar: config/, secrets.json") == 1
    assert project_rules.forbidden(project / "config" / "ajustes.yaml") == "config/"
    assert project_rules.forbidden(project / "app" / "secrets.json") == "secrets.json"
    assert project_rules.forbidden(project / "app" / "main.py") is None
    assert project_rules.forbidden(None) is None


def test_after_edit_commands_run_and_their_failures_reach_the_agent(tmp_path):
    project = _project(tmp_path)
    check = tmp_path / "check.py"
    check.write_text("import sys\nsrc = open(sys.argv[1]).read()\nprint('TODO encontrado') if 'TODO' in src "
                     "else None\nsys.exit(1 if 'TODO' in src else 0)\n", encoding="utf-8")
    project_rules.add_request(f'/regla al editar *.py: "{sys.executable}" check.py {{archivo}}', project)
    good, bad = project / "app" / "bien.py", project / "app" / "mal.py"
    good.write_text("x = 1\n", encoding="utf-8")
    bad.write_text("x = 1  # TODO\n", encoding="utf-8")
    assert project_rules.after_edit(str(good)) is None
    note = agent_feedback.note_for("edit", json.dumps({"filePath": str(bad)}), "Edit applied successfully.")
    assert "reglas del proyecto" in note and "TODO encontrado" in note
    assert project_rules.after_edit(str(project / "notas.txt")) is None


def test_the_model_cannot_drop_the_rules_when_it_rewrites_the_card(tmp_path):
    before = "# P\n## A\n## Reglas de Chati\n\n- no tocar: config/\n"
    after = code_checks.project_notes("# P\n## A\nnuevo\n", before, None, "x", "y", [])
    assert "- no tocar: config/" in code_checks.section(after, "Reglas de Chati")


def test_the_guard_rejects_edits_the_rules_forbid(tmp_path):
    import main
    project = _project(tmp_path)
    project_rules.add_request("/regla no tocar: config/", project)
    perm = {"id": "p1", "permission": "edit", "patterns": ["config/ajustes.yaml"],
            "metadata": {"filepath": str(project / "config" / "ajustes.yaml")}}
    view = {"permissions": [perm], "directory": str(project), "steps": [], "task": "cambia el puerto"}
    with patch.object(main.opencode_client, "reply_permission") as reply, \
         patch.object(main.opencode_client, "continue_task") as cont:
        assert agent_watch._guard_permissions("http://x", "ses", view, 0)
    assert reply.call_args.args[2] == "reject" and "no tocar: config/" in cont.call_args.args[2]
