"""签名 cookie：不存 GitHub token，登录态自证。伪造与过期必须被拒。"""
import pytest

from app.feed import auth
from app import config

NOW = 1_700_000_000


def test_sign_then_verify_roundtrip():
    assert auth.verify(auth.sign(7, NOW), NOW) == (7, 0)


def test_sign_carries_epoch_kwarg():
    assert auth.verify(auth.sign(7, NOW, epoch=3), NOW) == (7, 3)


def test_tampered_payload_is_rejected():
    token = auth.sign(7, NOW)
    body, sig = token.split(".", 1)
    forged = auth.base64.urlsafe_b64encode(b"9:%d:0" % NOW).decode().rstrip("=")
    assert auth.verify(f"{forged}.{sig}", NOW) is None


def test_wrong_signature_is_rejected():
    token = auth.sign(7, NOW)
    body, _sig = token.split(".", 1)
    assert auth.verify(f"{body}.deadbeef", NOW) is None


def test_expired_token_is_rejected():
    old = auth.sign(7, NOW - config.SESSION_MAX_AGE - 10)
    assert auth.verify(old, NOW) is None


def test_garbage_token_is_rejected():
    for junk in ("", ".", "no-dot", "a.b.c", "!!!.???", "中文.签名"):
        assert auth.verify(junk, NOW) is None


def test_non_ascii_signature_is_rejected():
    """Starlette 以 latin-1 解码头，非 ASCII 签名段必须当作未登录，不抛 TypeError。"""
    assert auth.verify("abc.中文签名", NOW) is None
    assert auth.verify("abc.%sdeadbeef" % chr(255), NOW) is None


def test_secret_change_invalidates_tokens(monkeypatch):
    token = auth.sign(7, NOW)
    monkeypatch.setattr(config, "SESSION_SECRET", "another-secret")
    assert auth.verify(token, NOW) is None


def test_upsert_user_is_idempotent(conn):
    gh = {"id": 555, "login": "alaala", "avatar_url": "https://a/x.png"}
    first = auth.upsert_user(conn, gh)
    second = auth.upsert_user(conn, {**gh, "login": "alaala-daka"})
    assert first == second
    row = conn.execute("SELECT * FROM users WHERE id = ?", (first,)).fetchone()
    assert row["login"] == "alaala-daka"  # 改名同步


def test_upsert_user_preserves_bio(conn):
    """GitHub 侧刷新不能抹掉觅码本地签名。"""
    gh = {"id": 556, "login": "u", "avatar_url": ""}
    uid = auth.upsert_user(conn, gh)
    conn.execute("UPDATE users SET bio = '我的签名' WHERE id = ?", (uid,))
    auth.upsert_user(conn, gh)
    assert conn.execute("SELECT bio FROM users WHERE id = ?", (uid,)).fetchone()["bio"] == "我的签名"


def test_ensure_prod_secrets_rejects_default(monkeypatch):
    monkeypatch.setattr(config, "GITHUB_MOCK", False, raising=False)
    monkeypatch.setattr(config, "SESSION_SECRET", "dev-only-insecure-secret", raising=False)
    with pytest.raises(RuntimeError, match="SESSION_SECRET"):
        config.ensure_prod_secrets()


def test_ensure_prod_secrets_passes(monkeypatch):
    monkeypatch.setattr(config, "GITHUB_MOCK", True, raising=False)
    monkeypatch.setattr(config, "SESSION_SECRET", "dev-only-insecure-secret", raising=False)
    config.ensure_prod_secrets()  # mock 模式放行
    monkeypatch.setattr(config, "GITHUB_MOCK", False, raising=False)
    monkeypatch.setattr(config, "SESSION_SECRET", "a-real-secret", raising=False)
    config.ensure_prod_secrets()  # 已配置放行


def test_session_cookie_secure_in_prod(monkeypatch):
    """非 mock 模式下发的 OAuth state cookie 必须带 Secure(会话 cookie 同理,同一写法)。"""
    from app.feed.routes import me

    monkeypatch.setattr(config, "GITHUB_MOCK", False, raising=False)
    resp = me.oauth_entry()
    assert "secure" in resp.headers["set-cookie"].lower()

    monkeypatch.setattr(config, "GITHUB_MOCK", True, raising=False)
    resp = me.oauth_entry()
    assert "secure" not in resp.headers["set-cookie"].lower()


def test_token_carries_session_epoch(conn):
    uid = auth.upsert_user(conn, {"id": 901, "login": "e", "avatar_url": ""})
    token = auth.issue_token(conn, uid)
    assert auth.verify(token, NOW) == (uid, 0)


def test_revoke_all_blocks_current_user(conn):
    """verify 是纯计算不查库:吊销靠 current_user 的 epoch 比对,不是靠改密钥。"""
    from starlette.requests import Request

    uid = auth.upsert_user(conn, {"id": 902, "login": "e", "avatar_url": ""})
    token = auth.issue_token(conn, uid)
    scope = {"type": "http", "method": "GET", "path": "/api/me", "headers": [
        (b"cookie", f"{config.SESSION_COOKIE}={token}".encode())], "client": ("1.1.1.1", 1)}
    assert auth.current_user(Request(scope), conn)["id"] == uid
    auth.revoke_all(conn, uid)
    assert auth.current_user(Request(scope), conn) is None
    assert auth.verify(token, NOW) == (uid, 0)       # 签名层仍有效:吊销靠 epoch 比对,不是靠改密钥


def test_reissue_after_revoke_gets_new_epoch(conn):
    uid = auth.upsert_user(conn, {"id": 903, "login": "e", "avatar_url": ""})
    auth.revoke_all(conn, uid)
    auth.revoke_all(conn, uid)
    token = auth.issue_token(conn, uid)
    assert auth.verify(token, NOW) == (uid, 2)


def test_old_two_part_token_rejected():
    """格式变更:旧版 base64(user_id:issued) 无 epoch 段,一律按未登录。"""
    body = auth.base64.urlsafe_b64encode(b"7:%d" % NOW).decode().rstrip("=")
    token = f"{body}.{auth._sig(body)}"
    assert auth.verify(token, NOW) is None
