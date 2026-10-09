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


def _next_date(date_str: str) -> str:
    start, _ = day_bounds_utc(date_str)
    return time.strftime("%Y-%m-%d", time.gmtime(start + 86400))


def _days_of_month(conn: sqlite3.Connection, month_key: str, now: int) -> list[dict]:
    """该月已过 UTC 日（≤今日）：完成日优先 traffic_daily，当日/缺失日现算。"""
    y, m = int(month_key[:4]), int(month_key[5:7])
    ny, nm = (y + 1, 1) if m == 12 else (y, m + 1)
    today = today_utc(now)
    out = []
    date_str = f"{month_key}-01"
    stop = f"{ny:04d}-{nm:02d}-01"
    while date_str < stop and date_str <= today:
        if date_str != today:
            row = conn.execute(
                "SELECT * FROM traffic_daily WHERE date=?", (date_str,)).fetchone()
            if row:
                out.append(dict(row))
                date_str = _next_date(date_str)
                continue
        out.append(day_stats(conn, date_str))
        date_str = _next_date(date_str)
    return out


def _month_from_days(month_key: str, days: list[dict]) -> dict:
    return {
        "month": month_key,
        "pv": sum(s["pv"] for s in days),
        "uv_avg": round(sum(s["uv"] for s in days) / len(days), 2) if days else 0.0,
        "api_calls": sum(s["api_calls"] for s in days),
        "errors": sum(s["errors"] for s in days),
        "new_users": sum(s["new_users"] for s in days),
    }


def _month_keys(now: int, months: int) -> list[str]:
    t = time.gmtime(now)
    year, mon = t.tm_year, t.tm_mon
    out = []
    for _ in range(months):
        out.append(f"{year:04d}-{mon:02d}")
        mon -= 1
        if mon == 0:
            mon, year = 12, year - 1
    return list(reversed(out))


def day_series(conn: sqlite3.Connection, days: int, now: int | None = None) -> list[dict]:
    now = int(now if now is not None else time.time())
    today = today_utc(now)
    out = []
    for offset in range(days - 1, -1, -1):
        date_str = today_utc(now - offset * 86400)
        if date_str != today:
            row = conn.execute(
                "SELECT * FROM traffic_daily WHERE date=?", (date_str,)).fetchone()
            if row:
                out.append(dict(row))
                continue
        out.append(day_stats(conn, date_str))
    return out


def month_series(conn: sqlite3.Connection, months: int, now: int | None = None) -> list[dict]:
    now = int(now if now is not None else time.time())
    return [_month_from_days(k, _days_of_month(conn, k, now))
            for k in _month_keys(now, months)]


def year_view(conn: sqlite3.Connection, year: int, now: int | None = None) -> dict:
    now = int(now if now is not None else time.time())
    today = today_utc(now)
    months = []
    days: list[dict] = []
    for m in range(1, 13):
        month_key = f"{year:04d}-{m:02d}"
        mdays = _days_of_month(conn, month_key, now) if month_key <= today[:7] else []
        months.append(_month_from_days(month_key, mdays))
        days.extend(mdays)
    elapsed = len(days)
    year_pv = sum(s["pv"] for s in days)
    peak = max(days, key=lambda s: s["pv"]) if days else None
    summary = {
        "year": year,
        "year_pv": year_pv,
        "daily_pv_avg": round(year_pv / elapsed, 2) if elapsed else 0.0,
        "daily_uv_avg": (round(sum(s["uv"] for s in days) / elapsed, 2)
                         if elapsed else 0.0),
        "new_users_year": sum(s["new_users"] for s in days),
        "peak_day": ({"date": peak["date"], "pv": peak["pv"]}
                     if peak and peak["pv"] else None),
    }
    return {"year": year, "months": months, "summary": summary}


def yearly(conn: sqlite3.Connection, now: int | None = None) -> list[dict]:
    now = int(now if now is not None else time.time())
    years = {int(r["date"][:4]) for r in conn.execute("SELECT date FROM traffic_daily")}
    years.add(time.gmtime(now).tm_year)
    out = []
    for y in sorted(years):
        s = year_view(conn, y, now)["summary"]
        out.append({"year": y, "pv": s["year_pv"], "uv_avg": s["daily_uv_avg"]})
    return out


def year_pv(conn: sqlite3.Connection, year: int, now: int | None = None) -> int:
    """本年累计 PV 快路径（安全复审：overview 高频端点禁用 year_view 全年逐日扫描）。

    SUM 只统计 < 今日 的 traffic_daily 行 + 今日 live 补齐，防手工补聚合今日行时双计。
    """
    now = int(now if now is not None else time.time())
    total = conn.execute(
        "SELECT COALESCE(SUM(pv),0) AS n FROM traffic_daily"
        " WHERE date>=? AND date<? AND date<?",
        (f"{year:04d}-01-01", f"{year + 1:04d}-01-01", today_utc(now))).fetchone()["n"]
    if time.gmtime(now).tm_year == year:
        total += day_stats(conn, today_utc(now))["pv"]
    return int(total)
