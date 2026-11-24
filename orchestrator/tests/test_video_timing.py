import time
from unittest.mock import patch

import main
from chat import video_replies
from media import video_timing


def test_estimate_scales_with_frames_and_size_per_model(tmp_path):
    with patch.object(video_timing, "TIMES_FILE", tmp_path / "t.jsonl"):
        assert video_timing.estimate("ltx", 97, 768, 512) is None
        assert "primera vez" in video_timing.say(None)
        video_timing.record("ltx", 97, 768, 512, 120)
        assert round(video_timing.estimate("ltx", 241, 768, 512)) == round(120 * 241 / 97)
        assert video_timing.estimate("wan", 97, 768, 512) is None
    assert video_timing.say(300) == "Generando el vídeo: unos 5 min…"
    assert video_timing.say(20) == "Generando el vídeo: menos de un minuto…"


def test_long_videos_send_a_phone_notification():
    auth = {"user_id": "u1"}
    with patch.object(main.push, "has_devices", return_value=True), patch.object(main.push, "notify") as notify:
        video_replies.notify_if_long(auth, time.time() - 30, "rapido")
        assert not notify.called
        video_replies.notify_if_long(auth, time.time() - 400, "Tu vídeo de 10 s está listo.")
    assert notify.call_args.args[1:3] == ("🎬 Vídeo listo", "Tu vídeo de 10 s está listo.")
