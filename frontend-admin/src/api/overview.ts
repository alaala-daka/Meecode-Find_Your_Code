/**
 * GET /api/admin/overview 契约（Task 8）：9 项计数（含二期观测三字段）；缺键渲染 `—` 容错。
 * 九键全可选：缺键是运行时事实，渲染侧按 `—` 容错（不伪造 0）。
 */
export type Overview = {
  total_users?: number;
  new_users_today?: number;
  total_repos?: number;
  published_repos?: number;
  delisted_repos?: number;
  pending_comments?: number;
  online?: number;
  today_pv?: number;
  year_pv?: number;
};

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

export const getOverview = (): Promise<Overview> => request("/overview");
