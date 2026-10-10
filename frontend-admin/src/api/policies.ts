export type PolicyRow = {
  route_key: string;
  enabled: boolean;
  limit_per_min: number;
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

const jsonInit = (body: unknown): RequestInit => ({
  method: "PATCH",
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify(body),
});

export const getPolicies = (): Promise<{ data: PolicyRow[]; total: number }> =>
  request("/api-policies");

export const updatePolicy = (
  key: string,
  body: { enabled?: boolean; limit_per_min?: number },
): Promise<PolicyRow> => request(`/api-policies/${encodeURIComponent(key)}`, jsonInit(body));
