from accounts import auth_sessions


def test_create_and_get_session_roundtrip():
    token = auth_sessions.create_session("u1", "ana", "admin", b"clave-secreta", 1)

    session = auth_sessions.get_session(token)

    assert session["username"] == "ana"
    assert session["role"] == "admin"
    assert session["dek"] == b"clave-secreta"
    assert session["key_generation"] == 1


def test_get_session_returns_none_for_unknown_token():
    assert auth_sessions.get_session("token-que-no-existe") is None


def test_guest_session_has_no_username_and_ephemeral_dek():
    token = auth_sessions.create_guest_session()

    session = auth_sessions.get_session(token)

    assert session["role"] == "guest"
    assert session["username"] is None
    assert session["user_id"] is None
    assert isinstance(session["dek"], bytes)


def test_two_guest_sessions_get_different_deks():
    token1 = auth_sessions.create_guest_session()
    token2 = auth_sessions.create_guest_session()

    assert auth_sessions.get_session(token1)["dek"] != auth_sessions.get_session(token2)["dek"]


def test_destroy_session_removes_it():
    token = auth_sessions.create_session("u1", "ana", "user", b"clave", 1)
    auth_sessions.destroy_session(token)

    assert auth_sessions.get_session(token) is None


def test_destroy_unknown_session_does_not_raise():
    auth_sessions.destroy_session("no-existe")


def test_session_expires_after_ttl(monkeypatch):
    fake_now = [1000.0]
    monkeypatch.setattr(auth_sessions.time, "time", lambda: fake_now[0])

    token = auth_sessions.create_session("u1", "ana", "user", b"clave", 1)
    assert auth_sessions.get_session(token) is not None

    fake_now[0] += auth_sessions.SESSION_TTL_SECONDS + 1
    assert auth_sessions.get_session(token) is None


def test_destroy_all_sessions_for_user_only_affects_that_user():
    token_a1 = auth_sessions.create_session("u1", "ana", "user", b"clave-a1", 1)
    token_a2 = auth_sessions.create_session("u1", "ana", "user", b"clave-a2", 1)
    token_b = auth_sessions.create_session("u2", "otro", "user", b"clave-b", 1)

    auth_sessions.destroy_all_sessions_for_user("ana")

    assert auth_sessions.get_session(token_a1) is None
    assert auth_sessions.get_session(token_a2) is None
    assert auth_sessions.get_session(token_b) is not None


def test_a_remembered_session_survives_a_restart_and_only_opens_with_its_token(monkeypatch):
    token = auth_sessions.create_session("u1", "ana", "admin", b"clave-secreta", 1, remember=True)
    assert b"clave-secreta" not in auth_sessions.REMEMBERED.read_bytes()  # cifrada con el token
    monkeypatch.setattr(auth_sessions, "_sessions", {})  # reinicio del servidor
    session = auth_sessions.get_session(token)
    assert session["dek"] == b"clave-secreta" and session["username"] == "ana"
    assert auth_sessions.get_session("otro-token") is None
    plain = auth_sessions.create_session("u1", "ana", "admin", b"clave", 1)
    monkeypatch.setattr(auth_sessions, "_sessions", {})
    assert auth_sessions.get_session(plain) is None  # sin "Recordarme" no se guarda


def test_logout_and_password_change_forget_the_remembered_session(monkeypatch):
    token = auth_sessions.create_session("u1", "ana", "admin", b"k", 1, remember=True)
    auth_sessions.destroy_session(token)
    monkeypatch.setattr(auth_sessions, "_sessions", {})
    assert auth_sessions.get_session(token) is None
    token = auth_sessions.create_session("u1", "ana", "admin", b"k", 1, remember=True)
    auth_sessions.destroy_all_sessions_for_user("ana")
    monkeypatch.setattr(auth_sessions, "_sessions", {})
    assert auth_sessions.get_session(token) is None
