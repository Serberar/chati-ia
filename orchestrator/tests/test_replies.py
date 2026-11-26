import requests

from api import replies


def test_without_comfyui_the_user_is_told_how_to_add_images(tmp_path, monkeypatch):
    monkeypatch.setattr(replies.paths, "DATA_ROOT", tmp_path)
    assert "sin imágenes" in replies.generation_error_message("imagen", requests.ConnectionError("8188"))


def test_with_comfyui_installed_the_real_error_is_shown(tmp_path, monkeypatch):
    (tmp_path / "ComfyUI").mkdir()
    monkeypatch.setattr(replies.paths, "DATA_ROOT", tmp_path)
    assert "8188" in replies.generation_error_message("imagen", requests.ConnectionError("8188"))
