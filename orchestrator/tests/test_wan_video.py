import io
from unittest.mock import patch

import av
import numpy as np

from agents import video_agent
from models import model_registry


def _clip(frames=6, size=(64, 48)) -> bytes:
    out = io.BytesIO()
    with av.open(out, "w", format="mp4") as c:
        s = c.add_stream("libx264", rate=24)
        s.width, s.height, s.pix_fmt = size[0], size[1], "yuv420p"
        for _ in range(frames):
            for p in s.encode(av.VideoFrame.from_ndarray(np.zeros((size[1], size[0], 3), np.uint8), format="rgb24")):
                c.mux(p)
        for p in s.encode():
            c.mux(p)
    return out.getvalue()


def test_wan_is_the_automatic_choice_when_installed(tmp_path):
    (tmp_path / "checkpoints" / "ltxv").mkdir(parents=True)
    (tmp_path / "checkpoints" / "ltxv" / "ltx.safetensors").write_text("x")
    with patch.object(model_registry, "VID_DIR", tmp_path):
        assert model_registry.get_video_model(None).architecture == "ltxv"
        (tmp_path / "diffusion_models" / "wan").mkdir(parents=True)
        (tmp_path / "diffusion_models" / "wan" / "wan2.2_ti2v_5B_fp16.safetensors").write_text("x")
        (tmp_path / "diffusion_models" / "wan" / "bajando.safetensors.part").write_text("x")
        entry = model_registry.get_video_model(None)
    assert entry.id == "wan:wan2.2_ti2v_5B_fp16" and entry.comfy_path.endswith("wan2.2_ti2v_5B_fp16.safetensors")


def test_ten_seconds_with_wan_are_two_chained_takes_from_the_last_frame():
    agent = video_agent.VideoAgent("http://fake")
    wan = model_registry.ModelEntry("wan:m", "wan", "Wan 2.2", "m", "wan\\m.safetensors")
    submitted = []

    def fake_run(workflow, *a, **k):
        submitted.append(workflow)
        return _clip()
    with patch.object(model_registry, "get_video_model", return_value=wan), \
         patch.object(agent, "_run", side_effect=fake_run), \
         patch.object(agent, "upload_image", return_value="tramo.png"):
        assert round(agent.max_seconds(), 1) == 5.0
        agent.generate("A dog runs.", seconds=10, seed=5)
    assert len(submitted) == 2
    assert "start_image" not in submitted[0]["latent"]["inputs"]
    assert submitted[1]["latent"]["inputs"]["start_image"] == ["start_image", 0]
    assert submitted[1]["sampler"]["inputs"]["seed"] == 5
