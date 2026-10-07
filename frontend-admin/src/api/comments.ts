export type CommentStatus = "pending" | "visible" | "hidden" | "deleted";

export type CommentRow = {
  id: number;
  repo_id: number;
  repo_full_name: string;
  user_id: number;
  user_login: string;
  parent_id: number | null;
  content: string;
  status: CommentStatus;
  moderation_reason: string | null;
  screened: number;
  created_at: number;
};

export type CommentActionResult = {
  ok: boolean;
  status: string;
};

export type BulkHideResult = {
  ok: boolean;
  affected: number;
  not_found: number[];
  skipped: number[];
};

export type CommentStats = {
  pending: number;
  visible: number;
  hidden: number;
  deleted: number;
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
      /* 非 JSON 错误体时保留状态码 */
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

export const hideComment = (id: number | string): Promise<CommentActionResult> =>
  request(`/comments/${id}/hide`, { method: "POST" });

export const restoreComment = (id: number | string): Promise<CommentActionResult> =>
  request(`/comments/${id}/restore`, { method: "POST" });

export const deleteComment = (id: number | string): Promise<CommentActionResult> =>
  request(`/comments/${id}`, { method: "DELETE" });

export const bulkHideComments = (ids: number[]): Promise<BulkHideResult> =>
  request("/comments/bulk", { method: "POST", ...jsonInit({ ids, action: "hide" }) });

export const getCommentsStats = (): Promise<CommentStats> => request("/comments/stats");
