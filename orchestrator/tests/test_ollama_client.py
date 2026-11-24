import json
from unittest.mock import MagicMock, patch

import pytest
import requests

from agents.ollama_client import OllamaClient


def _fake_error_response(status_code=400, error_body=None, raw_text=""):
    resp = requests.Response()
    resp.status_code = status_code
    if error_body is not None:
        resp._content = json.dumps(error_body).encode()
    else:
        resp._content = raw_text.encode()
    return resp


def _fake_chat_response(content="hola"):
    resp = MagicMock()
    resp.json.return_value = {"message": {"content": content}}
    return resp


def test_unload_sends_keep_alive_zero_for_the_given_model():
    client = OllamaClient("http://localhost:11434")
    with patch("agents.ollama_client.requests.post") as mock_post:
        client.unload("qwen3-coder:30b-cpu")

    mock_post.assert_called_once()
    args, kwargs = mock_post.call_args
    assert args[0] == "http://localhost:11434/api/generate"
    assert kwargs["json"] == {"model": "qwen3-coder:30b-cpu", "keep_alive": 0}


def test_unload_swallows_network_errors_without_raising():
    import requests

    client = OllamaClient("http://localhost:11434")
    with patch("agents.ollama_client.requests.post", side_effect=requests.ConnectionError("sin red")):
        client.unload("qwen3-coder:30b-cpu")


def test_chat_omits_think_from_payload_when_not_given():
    client = OllamaClient("http://localhost:11434")
    with patch("agents.ollama_client.requests.post", return_value=_fake_chat_response()) as mock_post:
        client.chat("qwen2.5:7b", [{"role": "user", "content": "hola"}])

    assert "think" not in mock_post.call_args.kwargs["json"]


def test_chat_includes_think_false_when_given():
    client = OllamaClient("http://localhost:11434")
    with patch("agents.ollama_client.requests.post", return_value=_fake_chat_response()) as mock_post:
        client.chat("qwen3:14b-cpu", [{"role": "user", "content": "hola"}], think=False)

    assert mock_post.call_args.kwargs["json"]["think"] is False


def test_chat_stream_includes_think_false_when_given():
    client = OllamaClient("http://localhost:11434")
    fake_resp = MagicMock()
    fake_resp.iter_lines.return_value = [b'{"message": {"content": "hola"}, "done": true}']
    with patch("agents.ollama_client.requests.post", return_value=fake_resp) as mock_post:
        list(client.chat_stream("qwen3:14b-cpu", [{"role": "user", "content": "hola"}], think=False))

    assert mock_post.call_args.kwargs["json"]["think"] is False


def test_chat_with_tools_includes_think_false_when_given():
    client = OllamaClient("http://localhost:11434")
    fake_resp = MagicMock()
    fake_resp.json.return_value = {"message": {"content": "hola"}}
    with patch("agents.ollama_client.requests.post", return_value=fake_resp) as mock_post:
        client.chat_with_tools("qwen3:14b-cpu", [{"role": "user", "content": "hola"}], [], think=False)

    assert mock_post.call_args.kwargs["json"]["think"] is False


def test_chat_raises_with_ollamas_actual_error_message():
    client = OllamaClient("http://localhost:11434")
    fake_resp = _fake_error_response(400, error_body={"error": "image bytes could not be decoded"})
    with patch("agents.ollama_client.requests.post", return_value=fake_resp), pytest.raises(requests.HTTPError, match="image bytes could not be decoded"):
        client.chat("qwen2.5vl:7b-cpu", [{"role": "user", "content": "hola"}])


def test_chat_stream_raises_with_ollamas_actual_error_message():
    client = OllamaClient("http://localhost:11434")
    fake_resp = _fake_error_response(400, error_body={"error": "context length exceeded"})
    with patch("agents.ollama_client.requests.post", return_value=fake_resp), pytest.raises(requests.HTTPError, match="context length exceeded"):
        list(client.chat_stream("qwen2.5vl:7b-cpu", [{"role": "user", "content": "hola"}]))


def test_raises_plain_status_error_when_body_has_no_json():
    client = OllamaClient("http://localhost:11434")
    fake_resp = _fake_error_response(500, raw_text="")
    with patch("agents.ollama_client.requests.post", return_value=fake_resp), pytest.raises(requests.HTTPError):
        client.chat("qwen2.5:7b", [{"role": "user", "content": "hola"}])


def test_models_in_the_no_think_list_never_think_unless_asked(monkeypatch):
    from agents import ollama_client
    monkeypatch.setattr(ollama_client, "NO_THINK_MODELS", {"qwen3:8b"})
    assert ollama_client._think("qwen3:8b", None) is False
    assert ollama_client._think("qwen3:8b", True) is True
    assert ollama_client._think("qwen2.5:7b", None) is None


def test_while_an_image_is_generating_the_models_run_on_the_cpu():
    from agents.ollama_client import OllamaClient
    client = OllamaClient("http://x")
    try:
        OllamaClient.gpu_busy = staticmethod(lambda: True)
        with patch("agents.ollama_client.requests.post", return_value=_fake_chat_response()) as mock_post:
            client.chat("qwen3:8b", [{"role": "user", "content": "hola"}])
        assert mock_post.call_args.kwargs["json"]["options"]["num_gpu"] == 0
        with patch("agents.ollama_client.requests.post") as mock_post:
            client.preload("qwen3:8b")
        mock_post.assert_not_called()
        OllamaClient.gpu_busy = staticmethod(lambda: False)
        with patch("agents.ollama_client.requests.post", return_value=_fake_chat_response()) as mock_post:
            client.chat("qwen3:8b", [{"role": "user", "content": "hola"}])
        assert "num_gpu" not in mock_post.call_args.kwargs["json"]["options"]
    finally:
        OllamaClient.gpu_busy = None
