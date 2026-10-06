export type RepoStatus = "published" | "pending_claim" | "delisted";

export type RepoAction = "publish" | "delist" | "restore";

export type RepoRow = {
  id: number;
  github_id: number;
  full_name: string;
  owner_login: string;
  language: string | null;
  stars: number;
  source: string;
  status: RepoStatus;
  category: string;
  quality: number;
  tagline_zh: string;
  impression_count: number;
  repo_view_count: number;
  published_at: number;
};

export type RepoEditPayload = {
  category: string;
  quality: number | null;
  tagline_zh: string;
};

export type RepoActionResult = {
  ok: boolean;
  status: string;
};

/** 分类枚举（镜像 backend/app/config.py CATEGORIES，配置即枚举不建表）。 */
export const REPO_CATEGORIES: readonly string[] = [
  "开发工具",
  "Web 应用",
  "AI 与机器学习",
  "系统与底层",
  "数据处理",
  "游戏与图形",
  "学习资源",
  "其他",
];

const API_URL = "/api/admin";

const request = async <T>(path: string, init: RequestInit = {}): Promise<T> => {
  const res = await fetch(`${API_URL}${path}`, { credentials: "include", ...init });
  if (!res.ok) {
    let detail: string | undefined;
    try {
      const body = (await res.json()) as { detail?: unknown };
      if (typeof body?.detail === "string") detail = body.detail;
    } catch {
      /* 无 JSON 错误体时回落状态码 */
    }
    throw Object.assign(new Error(detail ?? `请求失败（HTTP ${res.status}）`), {
      status: res.status,
      statusCode: res.status,
    });
  }
  return (await res.json()) as T;
};

const jsonInit = (body: unknown): RequestInit => ({
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify(body),
});

export const updateRepo = (
  id: number | string,
  payload: RepoEditPayload,
): Promise<{ ok: boolean }> => request(`/repos/${id}`, { method: "PATCH", ...jsonInit(payload) });

export const repoStateAction = (
  id: number | string,
  action: RepoAction,
): Promise<RepoActionResult> => request(`/repos/${id}/${action}`, { method: "POST" });
