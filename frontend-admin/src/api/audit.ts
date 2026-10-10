export type AuditRow = {
  id: number;
  ts: string;
  admin_login: string;
  action: string;
  target_type: string;
  target_id: string | null;
  detail: unknown;
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

export const getAuditLogs = (params: {
  action?: string;
  admin?: string;
  page?: number;
  page_size?: number;
}): Promise<{ data: AuditRow[]; total: number }> => {
  const qs = new URLSearchParams();
  if (params.action) qs.set("action", params.action);
  if (params.admin) qs.set("admin", params.admin);
  qs.set("page", String(params.page ?? 1));
  qs.set("page_size", String(params.page_size ?? 20));
  return request(`/audit-logs?${qs.toString()}`);
};
