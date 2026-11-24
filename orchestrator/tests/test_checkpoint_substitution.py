from agents import image_agent, video_agent
from models import model_registry


def _make_image_tree(tmp_path, monkeypatch):
    img = tmp_path / "img"
    vid = tmp_path / "vid"
    (img / "checkpoints" / "sdxl").mkdir(parents=True)
    (img / "diffusion_models" / "flux").mkdir(parents=True)
    (img / "checkpoints" / "sdxl" / "modelo.safetensors").write_bytes(b"x")
    (img / "diffusion_models" / "flux" / "modelo.gguf").write_bytes(b"x")
    monkeypatch.setattr(model_registry, "IMG_DIR", img)
    monkeypatch.setattr(model_registry, "VID_DIR", vid)
    return img, vid


def _make_video_tree(tmp_path, monkeypatch):
    img = tmp_path / "img"
    vid = tmp_path / "vid"
    (vid / "checkpoints" / "ltxv").mkdir(parents=True)
    (vid / "checkpoints" / "ltxv" / "modelo.safetensors").write_bytes(b"x")
    monkeypatch.setattr(model_registry, "IMG_DIR", img)
    monkeypatch.setattr(model_registry, "VID_DIR", vid)
    return img, vid


def _capture_workflow(monkeypatch, module):
    captured = {}

    def fake_submit_and_wait(base_url, workflow, save_node, output_keys, timeout):
        captured["workflow"] = workflow
        return {"content": b"fake-bytes", "prompt_id": "fake"}

    monkeypatch.setattr(module, "submit_and_wait", fake_submit_and_wait)
    return captured


def _assert_no_unfilled_placeholders(workflow: dict):
    raw = str(workflow)
    assert "__CHECKPOINT_PATH__" not in raw, "quedo un placeholder de checkpoint sin rellenar"
    assert "__UNET_PATH__" not in raw, "quedo un placeholder de unet sin rellenar"


def test_image_agent_generate_fills_the_checkpoint_placeholder(tmp_path, monkeypatch):
    _make_image_tree(tmp_path, monkeypatch)
    captured = _capture_workflow(monkeypatch, image_agent)
    agent = image_agent.ImageAgent("http://fake")

    agent.generate("a cat", model_id="sdxl:modelo")

    _assert_no_unfilled_placeholders(captured["workflow"])
    assert "modelo.safetensors" in captured["workflow"]["checkpoint_loader"]["inputs"]["ckpt_name"]


def test_image_agent_generate_flux_fills_the_unet_placeholder(tmp_path, monkeypatch):
    _make_image_tree(tmp_path, monkeypatch)
    captured = _capture_workflow(monkeypatch, image_agent)
    agent = image_agent.ImageAgent("http://fake")

    agent.generate("a cat", model_id="flux:modelo")

    _assert_no_unfilled_placeholders(captured["workflow"])
    assert "modelo.gguf" in captured["workflow"]["unet_loader"]["inputs"]["unet_name"]


def test_image_agent_generate_raises_clearly_when_nothing_installed(tmp_path, monkeypatch):
    img = tmp_path / "img"
    vid = tmp_path / "vid"
    monkeypatch.setattr(model_registry, "IMG_DIR", img)
    monkeypatch.setattr(model_registry, "VID_DIR", vid)
    agent = image_agent.ImageAgent("http://fake")

    try:
        agent.generate("a cat")
        assert False, "deberia haber lanzado NoModelInstalledError"
    except image_agent.NoModelInstalledError:
        pass


def test_video_agent_generate_fills_the_checkpoint_placeholder(tmp_path, monkeypatch):
    _make_video_tree(tmp_path, monkeypatch)
    captured = _capture_workflow(monkeypatch, video_agent)
    agent = video_agent.VideoAgent("http://fake")

    agent.generate("a dog running")

    _assert_no_unfilled_placeholders(captured["workflow"])
    assert "modelo.safetensors" in captured["workflow"]["checkpoint_loader"]["inputs"]["ckpt_name"]


def test_video_agent_generate_raises_clearly_when_nothing_installed(tmp_path, monkeypatch):
    img = tmp_path / "img"
    vid = tmp_path / "vid"
    monkeypatch.setattr(model_registry, "IMG_DIR", img)
    monkeypatch.setattr(model_registry, "VID_DIR", vid)
    agent = video_agent.VideoAgent("http://fake")

    try:
        agent.generate("a dog running")
        assert False, "deberia haber lanzado NoModelInstalledError"
    except image_agent.NoModelInstalledError:
        pass


def test_seconds_become_ltx_frame_counts():
    assert [video_agent.frames_for(s) for s in (1, 4, 10, 30)] == [25, 97, 241, 257]
    assert all((video_agent.frames_for(s) - 1) % 8 == 0 for s in (0.5, 2.3, 7))
