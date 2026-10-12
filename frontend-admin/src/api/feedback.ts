const API_URL = "/api/admin";

const request = async <T>(path: string, init: RequestInit = {}): Promise<T> => {
  const res = await fetch(`${API_URL}${path}`, { credentials: "include", ...init });
  if (!res.ok) {
    let detail: string | undefined;
    try {
      const body = (await res.json()) as { detail?: unknown };
      if (typeof body?.detail === "string") detail = body.detail;
    } catch {
      /* 非 JSON 错误体时保留状态码文案 */
    }
    throw Object.assign(new Error(detail ?? `请求失败（HTTP ${res.status}）`), {
      status: res.status,
      statusCode: res.status,
    });
  }
  return (await res.json()) as T;
};

const jsonInit = (body: unknown, method = "POST"): RequestInit => ({
  method,
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify(body),
});

export type FeedbackCategory = "bug" | "suggest" | "other";
export type FeedbackStatus = "pending" | "done" | "ignored";

export type FeedbackRow = {
  id: number;
  user_id: number;
  user_login: string;
  category: FeedbackCategory;
  body: string;
  status: FeedbackStatus;
  note: string;
  reply_count: number;
  created_at: number;
  updated_at: number;
};

export type FeedbackReply = {
  id: number;
  body: string;
  author_login: string;
  created_at: number;
  read_at: number | null;
};

export type FeedbackDetail = FeedbackRow & {
  contact: string | null;
  replies: FeedbackReply[];
};

export type FeedbackPatchPayload = { status?: FeedbackStatus; note?: string };

export const FEEDBACK_CATEGORIES: readonly FeedbackCategory[] = ["bug", "suggest", "other"];
export const FEEDBACK_STATUSES: readonly FeedbackStatus[] = ["pending", "done", "ignored"];

export const getFeedback = (params: {
  status?: string;
  category?: string;
  q?: string;
  page?: number;
  page_size?: number;
}): Promise<{ data: FeedbackRow[]; total: number }> => {
  const qs = new URLSearchParams();
  if (params.status) qs.set("status", params.status);
  if (params.category) qs.set("category", params.category);
  if (params.q) qs.set("q", params.q);
  qs.set("page", String(params.page ?? 1));
  qs.set("page_size", String(params.page_size ?? 20));
  return request(`/feedback?${qs.toString()}`);
};

export const getFeedbackDetail = (id: number): Promise<FeedbackDetail> =>
  request(`/feedback/${id}`);

export const updateFeedback = (id: number, payload: FeedbackPatchPayload): Promise<{ ok: true }> =>
  request(`/feedback/${id}`, jsonInit(payload, "PATCH"));

export const createFeedbackReply = (id: number, body: string): Promise<{ id: number }> =>
  request(`/feedback/${id}/replies`, jsonInit({ body }));
