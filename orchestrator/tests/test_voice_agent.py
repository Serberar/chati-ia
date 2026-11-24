import pytest

from agents.voice_agent import VoiceAgent


@pytest.fixture(scope="module")
def voice_agent():
    return VoiceAgent()


@pytest.mark.slow
def test_tts_produces_valid_audio(tmp_path, voice_agent):
    out_path = tmp_path / "test.wav"
    voice_agent.speak("Hola, esto es una prueba.", str(out_path))

    assert out_path.exists()
    assert out_path.stat().st_size > 1000


@pytest.mark.slow
def test_tts_then_stt_roundtrip_preserves_meaning(tmp_path, voice_agent):
    text = "El cielo esta despejado hoy en Zaragoza."
    audio_path = tmp_path / "roundtrip.wav"
    voice_agent.speak(text, str(audio_path))

    transcript = voice_agent.transcribe(str(audio_path))

    assert transcript, "deberia devolver algo, no una cadena vacia"
    lowered = transcript.lower()
    assert "cielo" in lowered
    assert "zaragoza" in lowered
