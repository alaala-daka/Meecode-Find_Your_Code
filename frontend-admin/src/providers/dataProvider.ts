/**
 * dataProvider —— 后端契约归一化（Task 12 fix round 1）
 *
 * 后端 admin 列表端点（users/repos/comments/audit-logs）返回包络
 *   {"data": [...rows], "total": n}
 * 详情端点（/users/{id} 等）直接返回行对象（无包络）。
 * 而 @refinedev/simple-rest v6 的 getList 把响应体当行数组、total 取
 * `x-total-count` 头 —— 裸用会得到 data={data,total}、total=undefined。
 * 故读方法自定义，映射如下：
 *
 * | 方法 | 请求 | 响应映射 |
 * |---|---|---|
 * | getList | GET /api/admin/{resource}?page=&page_size=&<filters> | unwrap：{data: body.data ?? body, total: body.total ?? rows.length} |
 * | getMany | 逐 id 调 getOne（后端无 id-in 端点，`?id=` 会被忽略返回第一页） | 行对象直接汇总 {data: rows} |
 * | getOne | GET /api/admin/{resource}/{id} | 行对象**原样透传**（详情端点无包络，不 unwrap） |
 * | create/update/deleteOne/custom/getApiUrl | 沿用 simple-rest 基座（axios withCredentials） | 响应体原样透传（useCustom 场景无包络，不 unwrap） |
 *
 * 请求侧：pagination → page/page_size（后端契约；simple-rest 默认 _start/_end 会被
 * FastAPI 忽略）；filters → field=value（eq/contains 语义由后端 q/status 处理，其余
 * operator 与 or/and 后端无对应能力，抛错）；sorters 不下发（后端列表固定 id/ts 降序）。
 * 错误：非 2xx 抛 Error 带 status/statusCode，供 authProvider.onError 判 401。
 */
import type {
  BaseRecord,
  DataProvider,
  GetListParams,
  GetListResponse,
  GetManyParams,
  GetManyResponse,
  GetOneParams,
  GetOneResponse,
} from "@refinedev/core";
import axios from "axios";
import simpleRest from "@refinedev/simple-rest";

const API_URL = "/api/admin";

const httpClient = axios.create({ withCredentials: true });

const base = simpleRest(API_URL, httpClient);

const request = async (path: string): Promise<unknown> => {
  const res = await fetch(`${API_URL}${path}`, { credentials: "include" });
  if (!res.ok) {
    throw Object.assign(new Error(`请求失败（HTTP ${res.status}）`), {
      status: res.status,
      statusCode: res.status,
    });
  }
  return res.json();
};

type ListBody = { data?: unknown; total?: unknown };

const unwrapList = (body: unknown): { rows: unknown[]; total: number } => {
  if (Array.isArray(body)) return { rows: body, total: body.length };
  const envelope = (body ?? {}) as ListBody;
  const rows = Array.isArray(envelope.data) ? envelope.data : [];
  return { rows, total: typeof envelope.total === "number" ? envelope.total : rows.length };
};

const getList = async <TData extends BaseRecord = BaseRecord>(
  params: GetListParams,
): Promise<GetListResponse<TData>> => {
  const query = new URLSearchParams();
  const { pagination, filters, resource } = params;
  if (pagination) {
    query.set("page", String(pagination.currentPage ?? 1));
    query.set("page_size", String(pagination.pageSize ?? 10));
  }
  for (const filter of filters ?? []) {
    if (!("field" in filter)) {
      throw new Error(`不支持的筛选：${filter.operator}`);
    }
    if (filter.operator !== "eq" && filter.operator !== "contains") {
      throw new Error(`不支持的筛选算子：${filter.operator}`);
    }
    if (filter.value != null) {
      query.set(filter.field, String(filter.value));
    }
  }
  const qs = query.toString();
  const { rows, total } = unwrapList(await request(`/${resource}${qs ? `?${qs}` : ""}`));
  return { data: rows as TData[], total };
};

const getOne = async <TData extends BaseRecord = BaseRecord>(
  params: GetOneParams,
): Promise<GetOneResponse<TData>> => {
  const row = (await request(`/${params.resource}/${params.id}`)) as TData;
  return { data: row };
};

const getMany = async <TData extends BaseRecord = BaseRecord>(
  params: GetManyParams,
): Promise<GetManyResponse<TData>> => {
  const data = await Promise.all(
    params.ids.map((id) => getOne<TData>({ resource: params.resource, id }).then((r) => r.data)),
  );
  return { data };
};

export const dataProvider: DataProvider = {
  ...base,
  getList,
  getMany,
  getOne,
};
