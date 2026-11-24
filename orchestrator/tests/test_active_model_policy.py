from unittest.mock import patch

import main
from models import gpu_memory


def _reset():
    gpu_memory._active_heavy_model = None


def test_first_heavy_model_loads_without_unloading_anything():
    _reset()
    with patch.object(main.ollama, "unload") as mock_unload:
        gpu_memory.ensure_active_model("qwen3-coder:30b-cpu")

    mock_unload.assert_not_called()
    assert gpu_memory._active_heavy_model == "qwen3-coder:30b-cpu"


def test_switching_to_a_different_heavy_model_unloads_the_old_one():
    _reset()
    gpu_memory._active_heavy_model = "qwen3-coder:30b-cpu"
    with patch.object(main.ollama, "unload") as mock_unload:
        gpu_memory.ensure_active_model("qwen3:14b-cpu")

    mock_unload.assert_called_once_with("qwen3-coder:30b-cpu")
    assert gpu_memory._active_heavy_model == "qwen3:14b-cpu"


def test_repeating_the_same_heavy_model_does_not_unload():
    _reset()
    gpu_memory._active_heavy_model = "qwen3-coder:30b-cpu"
    with patch.object(main.ollama, "unload") as mock_unload:
        gpu_memory.ensure_active_model("qwen3-coder:30b-cpu")

    mock_unload.assert_not_called()
    assert gpu_memory._active_heavy_model == "qwen3-coder:30b-cpu"


def test_switching_to_the_light_shared_model_frees_the_heavy_one():
    _reset()
    gpu_memory._active_heavy_model = "qwen3-coder:30b-cpu"
    with patch.object(main.ollama, "unload") as mock_unload:
        gpu_memory.ensure_active_model(gpu_memory.LIGHT_MODEL)

    mock_unload.assert_called_once_with("qwen3-coder:30b-cpu")
    assert gpu_memory._active_heavy_model is None


def test_light_model_calls_stay_cheap_when_nothing_heavy_was_loaded():
    _reset()
    with patch.object(main.ollama, "unload") as mock_unload:
        gpu_memory.ensure_active_model(gpu_memory.LIGHT_MODEL)

    mock_unload.assert_not_called()
    assert gpu_memory._active_heavy_model is None
