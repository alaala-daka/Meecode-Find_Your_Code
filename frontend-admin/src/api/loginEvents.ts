export type LoginEventRow = {
  id: number;
  ts: number;
  user_id: number | null;
  login: string;
  ip_hash: string;
  event: "login" | "logout";
  ok: number;
};

const API_URL = "/api/admin";

const request = async <T>(path: string): Promise<T> => {
  const res = await fetch(`${API_URL}${path}`, { credentials: "include" });
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

export const getLoginEvents = (params: {
  q?: string;
  ok?: string;
  event?: string;
  from?: string;
  to?: string;
  ip?: string;
  page?: number;
  page_size?: number;
}): Promise<{ data: LoginEventRow[]; total: number }> => {
  const qs = new URLSearchParams();
  if (params.q) qs.set("q", params.q);
  if (params.ok) qs.set("ok", params.ok);
  if (params.event) qs.set("event", params.event);
  if (params.from) qs.set("from", params.from);
  if (params.to) qs.set("to", params.to);
  if (params.ip) qs.set("ip", params.ip);
  qs.set("page", String(params.page ?? 1));
  qs.set("page_size", String(params.page_size ?? 20));
  return request(`/login-events?${qs.toString()}`);
};
