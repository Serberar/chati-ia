from unittest.mock import MagicMock

import pytest

from chat import prompt_writer


def _ollama(answer):
    ollama = MagicMock()
    ollama.chat.return_value = answer
    return ollama


def test_image_prompt_reads_description_and_format():
    ollama = _ollama('{"prompt": "A realistic photo of a dog in the snow.", "formato": "vertical"}')
    prompt, size = prompt_writer.image_prompt(ollama, "qwen3:8b", "un perro en la nieve")
    assert prompt == "A realistic photo of a dog in the snow."
    assert size == (832, 1216)
    assert "un perro en la nieve" in ollama.chat.call_args.args[1][0]["content"]


@pytest.mark.parametrize("answer", ["no se", '{"formato": "rarisimo"}', '{"prompt": ""}'])
def test_image_prompt_falls_back_to_the_request_as_is(answer):
    prompt, size = prompt_writer.image_prompt(_ollama(answer), "qwen3:8b", "un perro")
    assert prompt == "un perro"
    assert size == (1024, 1024)


@pytest.mark.parametrize("text,expected", [
    ("A realistic phone wallpaper featuring mountains, soft light.", "A realistic image of mountains, soft light."),
    ("A friendly dragon for my nephew, cartoon style.", "A friendly dragon, cartoon style."),
    ("A cake for my little sister with candles.", "A cake with candles."),
    ("A bouquet of roses for the table.", "A bouquet of roses for the table."),
])
def test_purpose_phrases_are_removed(text, expected):
    assert prompt_writer._clean(text) == expected


@pytest.mark.live
@pytest.mark.parametrize("request_text,size", [
    ("un perro en la nieve", (1024, 1024)),
    ("hazme un fondo de pantalla para el movil con montañas", (832, 1216)),
    ("un paisaje panoramico de la costa", (1216, 832)),
])
def test_image_prompt_with_the_real_model(request_text, size):
    from agents.ollama_client import OllamaClient
    prompt, got = prompt_writer.image_prompt(OllamaClient("http://127.0.0.1:11434"), "qwen3:8b", request_text)
    assert got == size
    assert prompt.isascii() and len(prompt.split()) >= 8
    assert "wallpaper" not in prompt.lower()


def test_video_plan_reads_seconds_and_format_and_falls_back_safely():
    ollama = _ollama('{"prompt": "A dog runs.", "segundos": 8, "formato": "vertical"}')
    assert prompt_writer.video_plan(ollama, "qwen3:8b", "un perro corriendo, 8 segundos, para el movil") == \
        ("A dog runs.", 8.0, (512, 768))
    assert prompt_writer.video_plan(_ollama('{"prompt": "A dog runs.", "segundos": "no se"}'), "m", "x") == \
        ("A dog runs.", None, (768, 512))
    assert prompt_writer.video_plan(_ollama("sin json"), "m", "un perro") == ("un perro", None, (768, 512))
