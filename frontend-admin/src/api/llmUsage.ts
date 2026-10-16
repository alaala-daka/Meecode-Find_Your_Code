/**
 * GET /api/admin/llm/stats 契约（spec 2026-10-10 三期 §4.3）。
 * daily 区间逐日补零行、date 升序；models 按 calls 降序；repos_top 仅 repo_id 非空行、
 * tokens 降序取 10，name 缺仓库行时后端已回填「仓库 #<repo_id>」。纯观测，无写接口。
 */
export type LlmDailyRow = {
  date: string;
  calls: number;
  prompt_tokens: number;
  completion_tokens: number;
  errors: number;
  avg_latency_ms: number;
};

export type LlmModelRow = { model: string; calls: number; tokens: number };

export type LlmRepoRow = { repo_id: number; name: string; calls: number; tokens: number };

export type LlmStats = {
  daily: LlmDailyRow[];
  models: LlmModelRow[];
  repos_top: LlmRepoRow[];
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
      /* 非 JSON 错误体时保留状态码文案 */
    }
    throw Object.assign(new Error(detail ?? `请求失败（HTTP ${res.status}）`), {
      status: res.status,
      statusCode: res.status,
    });
  }
  return (await res.json()) as T;
};

export const getLlmStats = (from: string, to: string): Promise<LlmStats> =>
  request(`/llm/stats?from=${encodeURIComponent(from)}&to=${encodeURIComponent(to)}`);
