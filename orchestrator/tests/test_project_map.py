from coding import agent_tools


def test_map_lists_python_and_js_definitions_and_skips_venv(tmp_path):
    (tmp_path / "app.py").write_text("import os\n\ndef main(a, b):\n    pass\n\nclass Tienda:\n    def total(self):\n"
                                     "        return 0\n", encoding="utf-8")
    (tmp_path / "web").mkdir()
    (tmp_path / "web" / "ui.js").write_text("export function pintar(x) {}\nconst sumar = (a, b) => a + b;\n",
                                            encoding="utf-8")
    (tmp_path / "venv").mkdir()
    (tmp_path / "venv" / "lib.py").write_text("def no_sale(): pass\n", encoding="utf-8")
    (tmp_path / "README.md").write_text("# x\n", encoding="utf-8")
    out = agent_tools.project_map(str(tmp_path))
    assert "app.py (9 lineas)\n  def main(a, b)\n  class Tienda: total" in out
    assert "web/ui.js" in out and "pintar" in out and "sumar" in out
    assert "no_sale" not in out and "Otros archivos: README.md" in out
