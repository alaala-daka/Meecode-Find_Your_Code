"""访问埋点与流量口径（spec 2026-10-09-admin-panel-phase2-design.md §2）。

ip 只存 HMAC 哈希（密钥从 SESSION_SECRET 派生）；埋点写失败吞异常，绝不阻塞主请求。
日界线为 UTC 日（与 overview 的 strftime('now','start of day') 一致）。
"""
from __future__ import annotations

import calendar
import functools
import hashlib
import hmac
import logging
import sqlite3
import threading
import time

from . import config

log = logging.getLogger(__name__)

_IP_SALT = b"meecode-access-ip-v1"

ACCESS_FLUSH_SECONDS = 30.0
ACCESS_FLUSH_ROWS = 200
ACCESS_MAX_BUFFER = 10_000
ACCESS_RETENTION_DAYS = 30
DEFAULT_ONLINE_WINDOW_MINUTES = 5
LAST_ACTIVE_THROTTLE_SECONDS = 60


def ip_hash(ip: str) -> str:
    """HMAC 假名化；密钥经 PBKDF2 派生并 memoize（与 token 密封同强度，防弱 secret 离线爆破连坐会话）。"""
    return hmac.new(_ip_key(), ip.encode("utf-8"), hashlib.sha256).hexdigest()[:32]


@functools.lru_cache(maxsize=1)
def _ip_key() -> bytes:
    return hashlib.pbkdf2_hmac("sha256", config.SESSION_SECRET.encode("utf-8"),
                               _IP_SALT, 200_000, dklen=32)


def day_bounds_utc(date_str: str) -> tuple[int, int]:
    start = calendar.timegm(time.strptime(date_str, "%Y-%m-%d"))
    return start, start + 86400


def today_utc(now: int | None = None) -> str:
    return time.strftime("%Y-%m-%d", time.gmtime(now if now is not None else time.time()))


def day_stats(conn: sqlite3.Connection, date_str: str) -> dict:
    """单日口径（spec §2.2）：pv/uv 取 HIT 行，api_calls/errors 取 API 行。"""
    start, end = day_bounds_utc(date_str)
    row = conn.execute(
        "SELECT"
        " SUM(CASE WHEN method='HIT' THEN 1 ELSE 0 END) AS pv,"
        " COUNT(DISTINCT CASE WHEN method='HIT' THEN ip_hash END) AS uv,"
        " SUM(CASE WHEN method!='HIT' THEN 1 ELSE 0 END) AS api_calls,"
        " SUM(CASE WHEN method!='HIT' AND status_code>=500 THEN 1 ELSE 0 END) AS errors,"
        " COUNT(DISTINCT user_id) AS active_users"
        " FROM access_events WHERE ts>=? AND ts<?",
        (start, end),
    ).fetchone()
    new_users = conn.execute(
        "SELECT COUNT(*) AS n FROM users WHERE created_at>=? AND created_at<?",
        (start, end),
    ).fetchone()["n"]
    return {
        "date": date_str,
        "pv": int(row["pv"] or 0),
        "uv": int(row["uv"] or 0),
        "api_calls": int(row["api_calls"] or 0),
        "errors": int(row["errors"] or 0),
        "active_users": int(row["active_users"] or 0),
        "new_users": int(new_users),
    }


def config_get(conn: sqlite3.Connection, key: str, default: str) -> str:
    row = conn.execute("SELECT value FROM app_config WHERE key=?", (key,)).fetchone()
    return row["value"] if row else default


def online_window_minutes(conn: sqlite3.Connection) -> int:
    try:
        return max(1, int(config_get(
            conn, "online_window_minutes", str(DEFAULT_ONLINE_WINDOW_MINUTES))))
    except (ValueError, TypeError):
        return DEFAULT_ONLINE_WINDOW_MINUTES


def online_count(conn: sqlite3.Connection, window_minutes: int | None = None) -> int:
    window = window_minutes if window_minutes is not None else online_window_minutes(conn)
    cutoff = int(time.time()) - window * 60
    return conn.execute(
        "SELECT COUNT(DISTINCT ip_hash) AS n FROM access_events WHERE ts>=?",
        (cutoff,),
    ).fetchone()["n"]


class AccessWriter:
    """access_events 内存缓冲批量落库：30s 或 200 条触发；写失败吞异常（spec §8）。

    安全复审修订（2026-10-09）：
    - record 全路径吞异常（failures 计数），绝不让埋点把主请求打 500；
    - _buf 硬上限 ACCESS_MAX_BUFFER，满则丢新行计 failures（防内存 DoS）；
    - flush 在守护线程执行（dispatch 在事件循环线程，同步 SQLite I/O 会停摆全服务）。
    并发修订（2026-10-09 任务评审 F1/F2）：
    - single-flight：_flush_scheduled 防 record 洪峰刷出线程风暴与并发写连接；
    - _active_written/failures 全部锁内读写；last_active_at 按 MAX 语义写（防回拨）。
    """

    def __init__(self) -> None:
        self._buf: list[tuple[int, int | None, str, str, str, int]] = []
        self._active: dict[int, int] = {}
        self._active_written: dict[int, int] = {}
        self._lock = threading.Lock()
        self._flush_scheduled = False
        self._factory = None
        self._last_flush = time.time()
        self.failures = 0

    def bind(self, factory) -> None:
        self._factory = factory

    def reset(self) -> None:
        with self._lock:
            self._buf = []
            self._active = {}
            self._active_written = {}
            self._flush_scheduled = False
            self.failures = 0

    def record(self, *, ts: int, user_id: int | None, ip: str, path: str,
               method: str, status_code: int) -> None:
        try:
            digest = ip_hash(ip)  # 锁外算：首次 PBKDF2 不阻塞并发 record
            with self._lock:
                if len(self._buf) >= ACCESS_MAX_BUFFER:
                    self.failures += 1  # 满额丢新行：宁失真不炸内存
                    return
                self._buf.append((ts, user_id, digest, path, method, status_code))
                if user_id is not None:
                    self._active[user_id] = ts
                due = (len(self._buf) >= ACCESS_FLUSH_ROWS
                       or ts - self._last_flush >= ACCESS_FLUSH_SECONDS)
                spawn = due and not self._flush_scheduled
                if spawn:
                    self._flush_scheduled = True
            if spawn:
                try:
                    threading.Thread(target=self._flush_auto, daemon=True).start()
                except Exception:
                    with self._lock:
                        self._flush_scheduled = False  # 起线程失败须解除 single-flight，防永久停摆
                        self.failures += 1
                    log.exception("access_events flush 线程启动失败（fail-swallow）")
        except Exception:
            with self._lock:
                self.failures += 1
            log.exception("access_events 埋点失败（fail-swallow）")

    def _flush_auto(self) -> None:
        try:
            if self._factory is None:
                with self._lock:
                    self._flush_scheduled = False
                return
            try:
                conn = self._factory()
            except Exception:
                with self._lock:
                    self.failures += 1
                    self._flush_scheduled = False
                return
            try:
                self.flush(conn)
            finally:
                try:
                    conn.close()
                except Exception:
                    pass
        except Exception:
            log.exception("access_events 后台 flush 异常（fail-swallow）")

    def flush(self, conn: sqlite3.Connection) -> int:
        with self._lock:
            rows, self._buf = self._buf, []
            acts, self._active = self._active, {}
            self._last_flush = time.time()
            self._flush_scheduled = False  # single-flight 解除
        if not rows:
            return 0
        try:
            conn.executemany(
                "INSERT INTO access_events (ts, user_id, ip_hash, path, method, status_code)"
                " VALUES (?,?,?,?,?,?)", rows)
            writes = []
            with self._lock:
                for uid, ts in acts.items():
                    if ts - self._active_written.get(uid, 0) >= LAST_ACTIVE_THROTTLE_SECONDS:
                        self._active_written[uid] = ts
                        writes.append((uid, ts))
                if len(self._active_written) > 10_000:
                    self._active_written = {}
            for uid, ts in writes:
                conn.execute(
                    "UPDATE users SET last_active_at=? WHERE id=?"
                    " AND (last_active_at IS NULL OR last_active_at < ?)",
                    (ts, uid, ts))  # MAX 语义：并发乱序提交不回拨
            conn.commit()
        except Exception:
            with self._lock:
                self.failures += 1
            log.exception("access_events 写失败（fail-swallow）")
            return 0
        return len(rows)


writer = AccessWriter()
