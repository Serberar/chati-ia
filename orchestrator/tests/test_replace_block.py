from coding import agent_tools

SOURCE = '''import os


def total(xs):
    return sum(xs)


class Carrito:
    @property
    def total(self):
        return 0

    def vacio(self):
        return True
'''


def test_replaces_a_function_or_a_method_keeping_the_rest(tmp_path):
    f = tmp_path / "a.py"
    f.write_text(SOURCE, encoding="utf-8")
    assert agent_tools.replace_block(str(f), "total", "def total(xs):\n    return round(sum(xs), 2)\n") \
        .startswith("Hecho")
    assert agent_tools.replace_block(str(f), "Carrito.total", "@property\ndef total(self):\n    return 1\n") \
        .startswith("Hecho")
    text = f.read_text(encoding="utf-8")
    assert "return round(sum(xs), 2)" in text and "    @property\n    def total(self):\n        return 1\n" in text
    assert text.count("@property") == 1 and "def vacio(self)" in text and text.startswith("import os")


def test_does_not_touch_the_file_if_the_result_would_not_be_python(tmp_path):
    f = tmp_path / "a.py"
    f.write_text(SOURCE, encoding="utf-8")
    assert agent_tools.replace_block(str(f), "total", "def total(xs)\n    return 1\n").startswith("NO")
    assert "Hay: total, Carrito" in agent_tools.replace_block(str(f), "precio", "def precio(): pass")
    assert f.read_text(encoding="utf-8") == SOURCE
