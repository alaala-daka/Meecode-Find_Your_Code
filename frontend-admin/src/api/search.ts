export type SearchGroup<T> = { count: number; items: T[] };

export type SearchResponse = {
  users: SearchGroup<{ id: number; login: string; bio: string }>;
  repos: SearchGroup<{ id: number; name: string; title: string; description: string }>;
  comments: SearchGroup<{
    id: number;
    body: string;
    author_login: string;
    repo_id: number;
    hidden: boolean;
  }>;
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

export const globalSearch = (q: string): Promise<SearchResponse> =>
  request(`/search?q=${encodeURIComponent(q)}`);
