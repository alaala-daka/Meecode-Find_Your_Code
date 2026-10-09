/**
 * 流量观测 API 契约（spec 2026-10-09 §3）。
 * 7d/30d → days 日序列；12m/年度 → months（年度另含 summary）。
 */
export type DayStat = {
  date: string;
  pv: number;
  uv: number;
  new_users: number;
  active_users: number;
  api_calls: number;
  errors: number;
};

export type MonthStat = {
  month: string;
  pv: number;
  uv_avg: number;
  api_calls: number;
  errors: number;
  new_users: number;
};

export type YearSummary = {
  year: number;
  year_pv: number;
  daily_pv_avg: number;
  daily_uv_avg: number;
  new_users_year: number;
  peak_day: { date: string; pv: number } | null;
};

export type TrafficResponse = {
  range: string;
  days?: DayStat[];
  months?: MonthStat[];
  summary?: YearSummary;
};

export type ApiStatsBucket = {
  route_key: string;
  calls: number;
  errors: number;
  error_rate: number;
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

export const getTraffic = (range: string): Promise<TrafficResponse> =>
  request(`/traffic?range=${range}`);

export const getTrafficYearly = (): Promise<{
  years: { year: number; pv: number; uv_avg: number }[];
}> => request("/traffic/yearly");

export const getApiStats = (range: string): Promise<{
  range: string;
  buckets: ApiStatsBucket[];
}> => request(`/api-stats?range=${encodeURIComponent(range)}`);
