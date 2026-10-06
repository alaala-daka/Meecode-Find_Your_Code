"""审计写入器：落库正确性 + 失败不抛。"""
import json
import logging

from app.admin import audit


def test_record_audit_persists_row(conn):
    audit.record_audit(conn, admin_login="boss", action="user.ban", target_type="user",
                       target_id=7, detail={"mute_comment": True})
    row = conn.execute("SELECT * FROM audit_logs").fetchone()
    assert row["admin_login"] == "boss"
    assert row["action"] == "user.ban"
    assert row["target_id"] == "7"
    assert json.loads(row["detail"]) == {"mute_comment": True}


def test_record_audit_swallows_db_error(conn, caplog):
    class Boom:
        def execute(self, *a, **k):
            raise RuntimeError("db down")

    with caplog.at_level(logging.ERROR):
        audit.record_audit(Boom(), admin_login="boss", action="user.ban",
                           target_type="user", target_id=1)  # 不抛
    assert any("audit" in r.message.lower() or "db down" in r.message.lower()
               or "audit" in r.name.lower() for r in caplog.records)
