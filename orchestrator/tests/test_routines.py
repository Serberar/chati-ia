from unittest.mock import patch

from coding import routines


def test_builtin_and_saved_routines_expand(tmp_path):
    with patch.object(routines, "ROUTINES_DIR", tmp_path / "rutinas"):
        steps, only_look = routines.expand("/revisa precios.py")
        assert only_look and "SIN CAMBIAR NADA" in steps and steps.endswith("Se aplica a: precios.py")
        assert routines.expand("/inventada") is None and routines.expand("arregla /revisa") is None
        assert "guardada" in routines.save_request("/rutina limpia: borra los .pyc y pasa ruff")
        assert routines.expand("/limpia") == ("borra los .pyc y pasa ruff", False)
        routines.save_request("/rutina revisa: solo mira los tests")
        assert routines.expand("/Revisa") == ("solo mira los tests", False)
        assert "/limpia" in routines.listing() and "/commit" in routines.listing()
    assert routines.save_request("/revisa algo") is None

