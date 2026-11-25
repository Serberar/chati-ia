import hashlib
from pathlib import Path

import pytest

from infra import app_update


@pytest.fixture(autouse=True)
def _isolated(tmp_path, monkeypatch):
    monkeypatch.setattr(app_update, "CACHE_PATH", tmp_path / "app_update.json")
    monkeypatch.setattr(app_update, "DOWNLOAD_DIR", tmp_path / "updates")
    monkeypatch.setattr(app_update, "VERSION", "1.1.0")
    monkeypatch.setattr(app_update, "TOKEN_FILE", tmp_path / "github_token.txt")
    app_update.set_token("github_pat_prueba")


def _release(version="1.2.0", digest="sha256:abc", name=app_update.ASSET_NAME):
    return {"version": version, "notes": "cambios", "url": f"https://github.com/x/{name}",
            "sha256": digest.removeprefix("sha256:")}


def test_is_newer_compares_numbers_not_text():
    assert app_update.is_newer("1.10.0", "1.9.0")
    assert app_update.is_newer("1.1.1", "1.1")
    assert not app_update.is_newer("1.1.0", "1.1.0")
    assert not app_update.is_newer("1.0.9", "1.1.0")


def test_check_reports_a_newer_release(monkeypatch):
    monkeypatch.setattr(app_update, "_fetch_latest", lambda: _release())
    info = app_update.check()
    assert info["available"] and info["latest"] == "1.2.0" and info["current"] == "1.1.0"


def test_check_without_checksum_is_not_installable(monkeypatch):
    monkeypatch.setattr(app_update, "_fetch_latest", lambda: _release(digest=""))
    assert not app_update.check()["available"]


def test_check_uses_cache_unless_forced(monkeypatch):
    calls = []
    monkeypatch.setattr(app_update, "_fetch_latest", lambda: calls.append(1) or _release())
    app_update.check()
    app_update.check()
    assert len(calls) == 1
    app_update.check(force=True)
    assert len(calls) == 2


def test_check_network_error_is_reported(monkeypatch):
    def fail():
        raise app_update.requests.ConnectionError("sin red")
    monkeypatch.setattr(app_update, "_fetch_latest", fail)
    info = app_update.check()
    assert not info["available"] and "sin red" in info["error"]


class _FakeResponse:
    def __init__(self, body):
        self.body = body

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def raise_for_status(self):
        pass

    def iter_content(self, _size):
        yield self.body


def test_install_refuses_a_download_that_does_not_match(monkeypatch):
    monkeypatch.setattr(app_update, "_fetch_latest", lambda: _release(digest="sha256:" + "0" * 64))
    monkeypatch.setattr(app_update.requests, "get", lambda *a, **k: _FakeResponse(b"otro archivo"))
    started = []
    monkeypatch.setattr(app_update.os, "startfile", lambda *a: started.append(a), raising=False)
    with pytest.raises(app_update.UpdateError, match="no coincide"):
        app_update.install()
    assert not started
    assert not list(app_update.DOWNLOAD_DIR.iterdir())


def test_install_runs_the_verified_installer_in_update_mode(monkeypatch):
    body = b"instalador"
    monkeypatch.setattr(app_update, "_fetch_latest",
                        lambda: _release(digest="sha256:" + hashlib.sha256(body).hexdigest()))
    monkeypatch.setattr(app_update.requests, "get", lambda *a, **k: _FakeResponse(body))
    started = []
    monkeypatch.setattr(app_update.os, "startfile", lambda *a: started.append(a), raising=False)

    assert app_update.install() == "1.2.0"

    path, verb, args = started[0]
    assert verb == "open" and "/UPDATE=1" in args
    assert Path(path).read_bytes() == body


def test_updates_work_without_a_github_token_and_use_it_if_there_is_one(monkeypatch):
    seen = []

    class _Resp:
        status_code = 200

        def raise_for_status(self):
            pass

        def json(self):
            return {"tag_name": "v1.2.0", "assets": [{"name": app_update.ASSET_NAME, "url": "https://api/asset/1",
                                                      "browser_download_url": "https://github.com/x", "digest": "sha256:ab"}]}

    monkeypatch.setattr(app_update.requests, "get", lambda url, **k: seen.append(k["headers"]) or _Resp())
    assert app_update._fetch_latest()["url"] == "https://api/asset/1"
    assert seen[0]["Authorization"] == "Bearer github_pat_prueba"
    app_update.TOKEN_FILE.unlink()
    info = app_update.check(force=True)
    assert "Authorization" not in seen[-1]
    assert info["error"] is None and info["latest"] == "1.2.0"


def test_an_expired_token_is_dropped_and_the_check_still_works(monkeypatch):
    calls = []

    class _Resp:
        def __init__(self, status):
            self.status_code = status

        def raise_for_status(self):
            pass

        def json(self):
            return {"tag_name": "v1.2.0", "assets": []}

    def fake_get(url, **k):
        calls.append(k["headers"])
        return _Resp(401 if "Authorization" in k["headers"] else 200)

    monkeypatch.setattr(app_update.requests, "get", fake_get)
    assert app_update._fetch_latest()["version"] == "1.2.0"
    assert len(calls) == 2 and not app_update.has_token()


def test_without_published_releases_it_says_so(monkeypatch):
    class _Resp:
        status_code = 404

    monkeypatch.setattr(app_update.requests, "get", lambda url, **k: _Resp())
    assert "ninguna version publicada" in app_update.check(force=True)["error"]


def test_install_without_newer_version_does_nothing(monkeypatch):
    monkeypatch.setattr(app_update, "_fetch_latest", lambda: _release(version="1.1.0"))
    with pytest.raises(app_update.UpdateError):
        app_update.install()
