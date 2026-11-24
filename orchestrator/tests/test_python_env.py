from unittest.mock import patch

from coding import agent_tools


def test_creates_the_venv_once_and_installs_inside_it(tmp_path):
    def fake_run(cmd, **_):
        if "venv" in cmd:
            (tmp_path / ".venv" / "Scripts").mkdir(parents=True)
            (tmp_path / ".venv" / "Scripts" / "python.exe").write_text("")
        return type("R", (), {"returncode": 0, "stdout": "ok", "stderr": ""})()

    with patch.object(agent_tools.subprocess, "run", side_effect=fake_run) as run:
        said = agent_tools.python_env(str(tmp_path), ["requests"])
        assert "Entorno creado" in said and "Instalado: requests" in said
        assert run.call_args_list[1].args[0][0].endswith(".venv/Scripts/python.exe")
        said = agent_tools.python_env(str(tmp_path))
        assert "creado" not in said and run.call_count == 2


def test_rejects_pip_options_disguised_as_packages(tmp_path):
    with patch.object(agent_tools.subprocess, "run") as run:
        assert "no validos" in agent_tools.python_env(str(tmp_path), ["--index-url=http://malo"])
        assert "no validos" in agent_tools.python_env(str(tmp_path), ["x; rm -rf /"])
    assert not run.called
