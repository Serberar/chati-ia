from unittest.mock import MagicMock, patch

import pytest

from agents import image_agent, video_agent
from api.replies import generation_error_message
from chat import prompt_writer
from media import content_guard


@pytest.mark.parametrize("text", [
    "desnúdala", "una mujer DESNUDA en la playa", "quítale la ropa a la chica", "quita la ropa", "en topless", "top-less",
    "una escena erótica", "foto porno", "a naked woman", "nude portrait", "n u d e".replace(" ", ""), "undress her",
    "woman with no clothes", "bare_breasts", "nsfw", "mujer sin ropa", "se desviste despacio",
])
def test_sexual_requests_are_blocked(text):
    assert content_guard.is_blocked(text)


@pytest.mark.parametrize("text", [
    "un perro en la nieve", "una playa al atardecer", "un retrato de una anciana con abrigo rojo", "olas rompiendo, 8 segundos",
    "a chest of drawers", "un sextante antiguo", "Essex en otoño", "un penalti en el último minuto", "una península",
    "un desierto", "dibuja un gato astronauta", "unos pantalones vaqueros en una percha", "",
])
def test_normal_requests_pass(text):
    assert not content_guard.is_blocked(text)


def test_the_request_is_blocked_before_asking_any_model():
    ollama = MagicMock()
    for write in (prompt_writer.image_prompt, prompt_writer.video_plan):
        with pytest.raises(content_guard.BlockedContent):
            write(ollama, "modelo", "una mujer desnuda")
    ollama.chat.assert_not_called()


def test_the_written_description_is_checked_too():
    """Aunque la peticion sea inocente, si el modelo escribe otra cosa no llega al generador."""
    image = image_agent.ImageAgent("http://x")
    video = video_agent.VideoAgent("http://x")
    with patch.object(image_agent, "submit_and_wait") as run_image, patch.object(video_agent, "submit_and_wait") as run_video:
        for call in (lambda: image.generate("a nude woman"), lambda: video.generate("a nude woman"),
                     lambda: video.generate_from_image("a nude woman", "foto.png")):
            with pytest.raises(content_guard.BlockedContent):
                call()
    run_image.assert_not_called()
    run_video.assert_not_called()


def test_the_user_gets_a_clear_answer():
    assert generation_error_message("generando la imagen", content_guard.BlockedContent()) == content_guard.MESSAGE
