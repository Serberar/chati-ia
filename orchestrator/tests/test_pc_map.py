from unittest.mock import patch

from coding import pc_map


def test_summary_lists_pythons_folders_and_missing_tools():
    pc_map._cache = None
    out = " -V:3.12 *        C:\\Python312\\python.exe\n -V:3.11          C:\\Python311\\python.exe\n"
    with patch.object(pc_map.subprocess, "run") as run, \
         patch.object(pc_map.shutil, "which", side_effect=lambda t: "C:/x/git.exe" if t == "git" else None), \
         patch.object(pc_map, "projects", return_value=["web en C:/p/web (prueba: npm test)"]):
        run.return_value.stdout = out
        text = pc_map.summary()
        assert pc_map.summary() is text and run.call_count == 1
    pc_map._cache = None
    assert "3.12 (el de por defecto) en C:/Python312/python.exe; 3.11 en C:/Python311/python.exe" in text
    assert "En el PATH: git;" in text and "NO estan instalados: node," in text
    assert "Proyectos del usuario: web en C:/p/web (prueba: npm test)." in text
    assert "Escritorio: " in text and "\\" not in text


def test_projects_are_found_with_how_to_test_them_skipping_venvs(tmp_path):
    (tmp_path / "a" / "api" / "tests").mkdir(parents=True)
    (tmp_path / "a" / "api" / "pyproject.toml").write_text("", encoding="utf-8")
    (tmp_path / "web").mkdir()
    (tmp_path / "web" / "package.json").write_text('{"scripts": {"test": "jest"}}', encoding="utf-8")
    (tmp_path / "venv" / "x").mkdir(parents=True)
    (tmp_path / "venv" / "x" / "requirements.txt").write_text("", encoding="utf-8")
    found = pc_map.projects([tmp_path])
    assert sorted(found) == [f"api en {(tmp_path / 'a' / 'api').as_posix()} (prueba: python -m pytest)",
                             f"web en {(tmp_path / 'web').as_posix()} (prueba: npm test)"]
