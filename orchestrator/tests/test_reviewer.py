from unittest.mock import patch

import main
from coding import agent_watch, checkpoints, reviewer

GUI_DIFF = """diff --git a/calcular_total.py b/calcular_total.py
--- a/calcular_total.py
+++ b/calcular_total.py
@@ -1,2 +1,4 @@
+import tkinter as tk
 import csv
"""
EXE_DIFF = """diff --git a/dist/Total.exe b/dist/Total.exe
new file mode 100644
Binary files differ
"""


def test_fixed_rules_catch_windows_and_builds_nobody_asked_for():
    fix = ["calcular_total.py da error, arreglalo"]
    assert "ventana" in reviewer.overreach(GUI_DIFF, fix)[0]
    assert reviewer.overreach(GUI_DIFF, ["hazle una ventana con un boton"]) == []
    assert "dist/Total.exe" in reviewer.overreach(EXE_DIFF, fix)[0]
    assert reviewer.overreach(EXE_DIFF, ["compila el .exe de nuevo"]) == []


def test_fixing_a_copy_instead_of_the_original_is_caught():
    diff = "diff --git a/lanzar_fixed.bat b/lanzar_fixed.bat\nnew file mode 100644\n+@echo off\n"
    found = reviewer.overreach(diff, ["lanzar.bat dice que no encuentra el archivo, arreglalo"])
    assert any("copia (lanzar_fixed.bat)" in p for p in found)
    assert reviewer.overreach(diff, ["haz una copia de lanzar.bat que funcione"]) == []
    new_helper = "diff --git a/utilidades.py b/utilidades.py\nnew file mode 100644\n+def x(): pass\n"
    assert reviewer.overreach(new_helper, ["arreglalo"]) == []


def test_cheats_are_caught_without_the_model():
    skipped = ("diff --git a/tests/test_precios.py b/tests/test_precios.py\n"
               "+@pytest.mark.skip(reason='luego')\n def test_descuento():\n-    assert aplicar(100, 20) == 80\n")
    found = reviewer.cheats(skipped)
    assert any("saltarlos" in p for p in found) and any("quitado 1" in p for p in found)
    silenced = "diff --git a/total.py b/total.py\n+    try:\n+        total += float(x)\n+    except:\n+        pass\n"
    assert any("except: pass" in p for p in reviewer.cheats(silenced))
    honest = ("diff --git a/precios.py b/precios.py\n-    return precio * pct / 100\n"
              "+    return precio * (1 - pct / 100)\n")
    assert reviewer.cheats(honest) == []
    assert reviewer.cheats("diff --git a/app.py b/app.py\n-    assert x > 0\n") == []


def test_the_model_verdict_is_read_safely():
    assert reviewer.parse('{"ok": true}') is None
    assert reviewer.parse('Vale: {"ok": false, "motivo": "Lo probaste desde su carpeta."}') == \
        "Lo probaste desde su carpeta."
    assert reviewer.parse("no se") is None


def test_review_uses_rules_first_and_then_the_model():
    view = {"task": "resumen.py falla si lo ejecuto desde otra carpeta, arreglalo", "steps": []}
    with patch.object(checkpoints, "diff_since_last", return_value=GUI_DIFF), \
         patch.object(main.ollama, "chat") as chat:
        assert "ventana" in agent_watch._review("ses", view, "")[0]
        assert not chat.called
    plain = "diff --git a/resumen.py b/resumen.py\n+ruta = Path(__file__).parent\n"
    with patch.object(checkpoints, "diff_since_last", return_value=plain), \
         patch.object(main.ollama, "chat", return_value='{"ok": false, "motivo": "Pruebalo desde otra carpeta."}'):
        assert agent_watch._review("ses", view, "cd gastos; python resumen.py → Gastos: 155") == ["Pruebalo desde otra carpeta."]
    with patch.object(checkpoints, "diff_since_last", return_value=""), patch.object(main.ollama, "chat") as chat:
        assert agent_watch._review("ses", view, "") == [] and not chat.called


def test_a_small_fix_that_rewrites_half_the_project_is_sent_back():
    big = "".join(f"diff --git a/m{i}.py b/m{i}.py\n" + "".join(f"+x{j} = {j}\n" for j in range(50)) for i in range(6))
    tests = "diff --git a/tests/test_m.py b/tests/test_m.py\n" + "+assert 1\n" * 300
    assert reviewer.diff_size(big + tests) == (300, 6)
    assert any("arreglo concreto" in p for p in reviewer.overreach(big, ["arregla el error al guardar"]))
    assert not any("arreglo concreto" in p for p in reviewer.overreach(big, ["refactoriza el guardado, falla"]))
    assert not any("arreglo concreto" in p for p in reviewer.overreach(big, ["añade exportar a Excel"]))
    assert not reviewer.overreach(tests, ["arregla el error al guardar"])


def test_files_outside_the_named_ones_need_a_reason():
    diff = ("diff --git a/precios.py b/precios.py\n+x\ndiff --git a/config.py b/config.py\n+y\n"
            "diff --git a/tests/test_precios.py b/tests/test_precios.py\n+z\ndiff --git a/AGENTS.md b/AGENTS.md\n+w\n")
    assert reviewer.out_of_scope(diff, ["arregla el descuento de precios.py"]) == ["config.py"]
    assert reviewer.out_of_scope(diff, ["el descuento sale mal"]) == []
    assert any("config.py" in p for p in reviewer.overreach(diff, ["arregla precios.py"]))


def test_files_the_program_moved_while_testing_are_not_out_of_scope():
    diff = ("diff --git a/ordenar.py b/ordenar.py\n+x\n"
            "diff --git a/descargas/factura.pdf b/descargas/factura.pdf\ndeleted file mode 100644\n"
            "Binary files a/descargas/factura.pdf and /dev/null differ\n"
            "diff --git a/descargas/notas.txt b/descargas/notas.txt\ndeleted file mode 100644\n-hola\n")
    assert reviewer.out_of_scope(diff, ["ordenar.py no mueve nada, arreglalo"]) == []
    assert reviewer.diff_size(diff) == (1, 1)
