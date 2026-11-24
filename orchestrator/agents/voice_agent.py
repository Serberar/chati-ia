import wave

from infra.paths import MODELS_DIR

PIPER_MODEL = MODELS_DIR / "voice" / "piper" / "es_ES-davefx-medium.onnx"


class VoiceAgent:

    def __init__(self):
        self._whisper = None
        self._piper = None

    @property
    def whisper(self):
        if self._whisper is None:
            try:
                from faster_whisper import WhisperModel
            except (ImportError, OSError) as exc:
                raise RuntimeError(f"La voz no esta disponible en este equipo: {exc}") from exc
            self._whisper = WhisperModel("large-v3-turbo", device="cpu", compute_type="int8")
        return self._whisper

    @property
    def piper(self):
        if self._piper is None:
            try:
                from piper import PiperVoice
            except (ImportError, OSError) as exc:
                raise RuntimeError(f"La voz no esta disponible en este equipo: {exc}") from exc
            self._piper = PiperVoice.load(str(PIPER_MODEL))
        return self._piper

    def transcribe(self, audio_path: str) -> str:
        segments, _info = self.whisper.transcribe(audio_path, language="es")
        return " ".join(seg.text.strip() for seg in segments).strip()

    def speak(self, text: str, out_path: str) -> None:
        with wave.open(out_path, "wb") as wav_file:
            self.piper.synthesize_wav(text, wav_file)
