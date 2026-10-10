export type ConfigRow = {
  key: string;
  value: string;
  version: number;
  updated_at: number;
  updated_by: string;
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

export const getConfig = (): Promise<{ data: ConfigRow[]; total: number }> =>
  request("/config");

export const updateConfig = (body: {
  key: string;
  value: string;
  version: number;
}): Promise<ConfigRow> =>
  request("/config", {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
