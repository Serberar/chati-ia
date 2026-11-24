from coding import agent_guard, prefetch


def _case(root, name, files):
    folder = root / "Desktop" / "pruebas" / name
    folder.mkdir(parents=True)
    for fname, text in files.items():
        (folder / fname).write_text(text, encoding="utf-8")
    return folder


def test_the_named_file_is_found_listed_and_read(tmp_path):
    _case(tmp_path, "facturas", {"calcular_total.py": "import csv\nprint(1)\n", "facturas.csv": "a;b\n1;2\n"})
    note = prefetch.facts("el calcular_total.py de pruebas/facturas me da error. arreglalo", [tmp_path / "Desktop"])
    assert "Carpeta " in note and "facturas.csv" in note
    assert "```\nimport csv\nprint(1)" in note and "DATOS del usuario" in note and "a;b" in note
    assert agent_guard.user_requests({"task": "arreglalo" + note, "steps": []}) == ["arreglalo"]


def test_no_note_when_nothing_is_named_or_the_name_is_ambiguous(tmp_path):
    _case(tmp_path, "a", {"main.py": "x = 1\n"})
    _case(tmp_path, "b", {"main.py": "y = 2\n"})
    assert prefetch.facts("ordena mis descargas", [tmp_path / "Desktop"]) == ""
    assert prefetch.facts("main.py no funciona", [tmp_path / "Desktop"]) == ""
    assert "x = 1" in prefetch.facts("el main.py de pruebas/a falla", [tmp_path / "Desktop"])
