"""系统配置 API：脱敏/拒密钥/版本锁/审计（Task 10）。"""


def test_config_list_masks_all_non_allowlisted_values(conn, client, admin):
    """白名单外一律 ***（安全复审：后缀启发式拦不住 DB_PASSWORD 等非标准命名）。"""
    conn.execute(
        "INSERT INTO app_config (key, value, version, updated_at, updated_by)"
        " VALUES ('GITHUB_CLIENT_SECRET','shh',1,0,'system')")
    conn.execute(
        "INSERT INTO app_config (key, value, version, updated_at, updated_by)"
        " VALUES ('DB_PASSWORD','hunter2',1,0,'system')")
    conn.commit()
    body = client.get("/api/admin/config").json()
    rows = {r["key"]: r for r in body["data"]}
    assert rows["online_window_minutes"]["value"] == "5"
    assert rows["GITHUB_CLIENT_SECRET"]["value"] == "***"
    assert rows["DB_PASSWORD"]["value"] == "***"
    assert set(rows["online_window_minutes"]) == {"key", "value", "version",
                                                  "updated_at", "updated_by"}


def test_config_patch_updates_and_audits(conn, client, admin):
    r = client.patch("/api/admin/config",
                     json={"key": "online_window_minutes", "value": "10", "version": 1})
    assert r.status_code == 200
    body = r.json()
    assert body["value"] == "10" and body["version"] == 2 and body["updated_by"] == "boss"
    a = conn.execute(
        "SELECT * FROM audit_logs WHERE action='config.update'").fetchone()
    assert a["target_id"] == "online_window_minutes" and a["detail"] == '{"value": "10"}'
    assert client.get("/api/admin/online").json()["window_minutes"] == 10


def test_config_patch_rejects_non_allowlisted_key(conn, client, admin):
    conn.execute("INSERT INTO app_config (key, value) VALUES ('DB_PASSWORD','x')")
    conn.commit()
    r = client.patch("/api/admin/config",
                     json={"key": "DB_PASSWORD", "value": "y", "version": 1})
    assert r.status_code == 400


def test_config_patch_version_conflict_409(conn, client, admin):
    r = client.patch("/api/admin/config",
                     json={"key": "online_window_minutes", "value": "9", "version": 99})
    assert r.status_code == 409
    row = conn.execute(
        "SELECT * FROM app_config WHERE key='online_window_minutes'").fetchone()
    assert row["value"] == "5" and row["version"] == 1


def test_config_patch_extra_forbid_and_unknown_key(conn, client, admin):
    assert client.patch("/api/admin/config",
                        json={"key": "online_window_minutes", "value": "1",
                              "version": 1, "nope": 1}).status_code == 422
    assert client.patch("/api/admin/config",
                        json={"key": "nope", "value": "1",
                              "version": 1}).status_code == 404


def test_config_endpoints_anonymous_401(conn, client):
    assert client.get("/api/admin/config").status_code == 401
    assert client.patch("/api/admin/config",
                        json={"key": "online_window_minutes", "value": "1",
                              "version": 1}).status_code == 401
