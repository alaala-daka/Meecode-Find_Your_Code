"""应用配置:LLM 服务走 OpenAI 兼容接口,全部经环境变量覆盖。信息流域参数一并集中在此。"""
from __future__ import annotations

import os

from dotenv import load_dotenv

load_dotenv()

# ---------- LLM(解读 + 精筛共用) ----------
LLM_BASE_URL: str = os.getenv("LLM_BASE_URL", "https://api.deepseek.com")
LLM_API_KEY: str = os.getenv("LLM_API_KEY", "")
LLM_MODEL: str = os.getenv("LLM_MODEL", "deepseek-chat")
# 精筛/AI 文案是 JSON 结构化任务,温度取低;伴读流式创作影响有限,统一 0.3
LLM_TEMPERATURE: float = float(os.getenv("LLM_TEMPERATURE", "0.3"))

# 模拟模式:不调用真实 LLM,返回确定性演示数据(离线开发/联调前端用)
LLM_MOCK: bool = os.getenv("LLM_MOCK", "").lower() in ("1", "true", "yes")

TAVILY_API_KEY: str = os.getenv("TAVILY_API_KEY", "")

# ---------- GitHub ----------
GITHUB_TOKEN: str = os.getenv("GITHUB_TOKEN", "")           # 平台 app token,读公开信息
GITHUB_CLIENT_ID: str = os.getenv("GITHUB_CLIENT_ID", "")   # OAuth 登录
GITHUB_CLIENT_SECRET: str = os.getenv("GITHUB_CLIENT_SECRET", "")
GITHUB_MOCK: bool = os.getenv("GITHUB_MOCK", "").lower() in ("1", "true", "yes")
GITHUB_API: str = "https://api.github.com"

# ---------- 会话 ----------
_DEV_SESSION_SECRET = "dev-only-insecure-secret"
SESSION_SECRET: str = os.getenv("SESSION_SECRET") or _DEV_SESSION_SECRET
SESSION_COOKIE: str = "mc_session"
SESSION_MAX_AGE: int = 30 * 24 * 3600
EXPLAIN_SESSION_TTL: int = int(os.getenv("EXPLAIN_SESSION_TTL", "7200"))   # 解读域会话滑动过期秒数
EXPLAIN_SESSION_MAX: int = int(os.getenv("EXPLAIN_SESSION_MAX", "512"))     # 进程内会话数上限(满额拒新)
FRONTEND_ORIGIN: str = os.getenv("FRONTEND_ORIGIN", "http://localhost:5173")
# CORS 白名单:FRONTEND_ORIGIN 之外加 127.0.0.1 变体(开发机同源不同 host)
CORS_ORIGINS: tuple[str, ...] = (FRONTEND_ORIGIN, "http://127.0.0.1:5173")

# ---------- 安全（限流 + Origin 校验，spec 2026-09-21） ----------
RATE_LIMIT_ENABLED: bool = os.getenv("RATE_LIMIT_ENABLED", "true").lower() in ("1", "true", "yes")
RATE_LIMIT_WINDOW: int = int(os.getenv("RATE_LIMIT_WINDOW", "60"))          # 窗口秒数
RATE_LIMIT_MAX_KEYS: int = int(os.getenv("RATE_LIMIT_MAX_KEYS", "10000"))   # 限流器键数上限
# CSRF 白名单与 CORS 同源：可信来源只维护一份
ALLOWED_ORIGINS: tuple[str, ...] = CORS_ORIGINS
# 仅这些对端的 XFF 末段可信(nginx 同机回环);其余来源忽略 XFF,取 socket 对端
TRUSTED_PROXIES: tuple[str, ...] = tuple(
    p.strip() for p in os.getenv("TRUSTED_PROXIES", "127.0.0.1,::1").split(",") if p.strip()
)

_RATE_LIMIT_DEFAULTS: dict[str, int] = {
    "llm": 20,       # LLM 计费端点：ai-draft + roots + 解读域四端点
    "session": 30,   # 白拿 session_id 是匿名打 LLM 的前置步
    "submit": 5,     # 投稿：GitHub 拉取 + LLM 精筛
    "interact": 60,  # 幂等互动写
    "browse": 240,   # feed/search/详情：匿名写库放大面
    "auth": 10,      # OAuth 跳转与回调
    "delist": 5,     # 下架：高危写操作，与 submit 同档
    "default": 120,  # 兜底
}


def _int_env(name: str, default: int) -> int:
    raw = os.getenv(name)
    try:
        return int(raw) if raw else default
    except ValueError:
        return default


# 每桶每 RATE_LIMIT_WINDOW 秒上限；环境变量 RATE_LIMIT_<桶名大写> 逐桶覆盖
RATE_LIMITS: dict[str, int] = {
    bucket: _int_env(f"RATE_LIMIT_{bucket.upper()}", limit)
    for bucket, limit in _RATE_LIMIT_DEFAULTS.items()
}


def ensure_prod_secrets() -> None:
    """生产模式 fail-fast:忘配 SESSION_SECRET 就拒启,避免会话 cookie 可被公开常量伪造。"""
    if not GITHUB_MOCK and SESSION_SECRET == _DEV_SESSION_SECRET:
        raise RuntimeError("GITHUB_MOCK=false 时必须设置 SESSION_SECRET(防止会话 cookie 被伪造)")


# ---------- 数据库 ----------
DB_PATH: str = os.getenv("DB_PATH", "meecode.db")

# ---------- 排序(可手调,冷启动后照日报调整) ----------
FRESHNESS_HALFLIFE_HOURS: float = 72.0  # 新鲜度半衰期
DEBUT_WINDOW_HOURS: int = 72            # 首发加权窗口
DEBUT_BOOST: float = 3.0                # 窗口内投稿加权倍数
NEUTRAL_QUALITY: int = 3                # LLM 未跑完/失败时的中性质量分
RESERVED_RATIO: float = 0.4             # 首页每页给投稿的预留位比例
FEED_PAGE_SIZE: int = 24
FEED_CANDIDATE_LIMIT: int = 500          # feed 候选池上限:拉够供排序,避免全表扫
RELATED_LIMIT: int = 4                   # 仓库页「相关推荐」条数

# ---------- 仓库详情与文件预览 ----------
MAX_FILE_CHARS: int = 200_000            # 超大文件截断阈值,避免塞爆响应
TREE_CACHE_SIZE: int = 512               # 文件树缓存条目上限
FILE_CACHE_SIZE: int = 1024              # 文件内容缓存条目上限

# ---------- 采集 ----------
CRAWL_DAILY_QUOTA: int = 30             # 每日入库上限(防冲淡投稿)
CRAWL_SCREEN_BUFFER: int = 5            # LLM 精筛 top-K 的缓冲量(K = 配额 + 缓冲)
CRAWL_RESCREEN_LIMIT: int = 10          # 每轮补筛 screened=0 的仓库数上限
CRAWL_CREATED_WITHIN_DAYS: int = 14
CRAWL_MIN_STARS: int = 3
CRAWL_LANGUAGES: tuple[str, ...] = (
    "Python", "TypeScript", "JavaScript", "Rust", "Go", "Java", "C++", "C", "Zig", "Swift",
)

# ---------- 规则粗筛门槛 ----------
MIN_README_CHARS: int = 500
MIN_CODE_FILES: int = 5
MAX_PUSHED_AGE_DAYS: int = 30
MIN_STAR_VELOCITY: float = 3.0           # star/周
MAX_OWNER_FOLLOWERS: int = 500           # 发掘无名者的启发式(仅采集端)
NAME_BLACKLIST: tuple[str, ...] = (
    "awesome", "tutorial", "homework", "100-days", "resume", "dotfiles", "leetcode",
)

# ---------- 分类枚举(配置即枚举,不建表) ----------
CATEGORIES: tuple[str, ...] = (
    "开发工具", "Web 应用", "AI 与机器学习", "系统与底层",
    "数据处理", "游戏与图形", "学习资源", "其他",
)


def llm_configured() -> bool:
    return LLM_MOCK or (bool(LLM_API_KEY) and "在这里填入" not in LLM_API_KEY)


def github_configured() -> bool:
    return GITHUB_MOCK or bool(GITHUB_TOKEN)
