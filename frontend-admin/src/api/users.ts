export const BAN_FOREVER = 253402300799;

export type UserCounts = {
  likes: number;
  favorites: number;
  visits: number;
  comments: number;
};

export type UserRow = {
  id: number;
  login: string;
  avatar_url: string | null;
  created_at: number;
  ban_comment_until: number | null;
  ban_submit_until: number | null;
  ban_note: string | null;
  admin_note: string | null;
  status: "normal" | "banned";
  counts: UserCounts;
};

export type RecentInteraction = {
  created_at: number;
  kind: string;
  repo_id: number;
};

export type UserDetail = UserRow & {
  recent_interactions: RecentInteraction[];
};

export type BanPayload = {
  mute_comment: boolean;
  mute_submit: boolean;
  until: number;
  note: string;
};

const API_URL = "/api/admin";

const request = async (path: string, init: RequestInit = {}): Promise<void> => {
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
};

const jsonInit = (body: unknown): RequestInit => ({
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify(body),
});

export const banUser = (id: number | string, payload: BanPayload): Promise<void> =>
  request(`/users/${id}/ban`, { method: "POST", ...jsonInit(payload) });

export const unbanUser = (id: number | string): Promise<void> =>
  request(`/users/${id}/unban`, { method: "POST" });

export const updateAdminNote = (id: number | string, admin_note: string): Promise<void> =>
  request(`/users/${id}`, { method: "PATCH", ...jsonInit({ admin_note }) });
