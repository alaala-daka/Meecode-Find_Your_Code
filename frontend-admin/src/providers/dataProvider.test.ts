import { describe, expect, it, vi } from "vitest";
import { dataProvider } from "./dataProvider";

const rows = [
  { id: 1, login: "boss", is_admin: true },
  { id: 2, login: "alice", is_admin: false },
];

describe("dataProvider.getList · {data,total} 包裹契约", () => {
  it("unwrap 包裹体 → {data: 行数组, total: 包络 total}", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(JSON.stringify({ data: rows, total: 5 }), { status: 200 }),
    );
    await expect(dataProvider.getList({ resource: "users" })).resolves.toEqual({
      data: rows,
      total: 5,
    });
  });

  it("请求打到 /api/admin/{resource} 且带 credentials", async () => {
    const fetchSpy = vi
      .spyOn(globalThis, "fetch")
      .mockResolvedValue(new Response(JSON.stringify({ data: [], total: 0 }), { status: 200 }));
    await dataProvider.getList({ resource: "users" });
    expect(fetchSpy).toHaveBeenCalledWith(
      "/api/admin/users",
      expect.objectContaining({ credentials: "include" }),
    );
  });

  it("pagination 映射 page/page_size", async () => {
    const fetchSpy = vi
      .spyOn(globalThis, "fetch")
      .mockResolvedValue(new Response(JSON.stringify({ data: [], total: 0 }), { status: 200 }));
    await dataProvider.getList({
      resource: "users",
      pagination: { currentPage: 2, pageSize: 10 },
    });
    expect(fetchSpy).toHaveBeenCalledWith(
      "/api/admin/users?page=2&page_size=10",
      expect.objectContaining({ credentials: "include" }),
    );
  });

  it("无包裹体（裸数组）时 total 回退数组长度", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(JSON.stringify(rows), { status: 200 }),
    );
    await expect(dataProvider.getList({ resource: "users" })).resolves.toEqual({
      data: rows,
      total: rows.length,
    });
  });
});

describe("dataProvider.getOne · 行对象透传", () => {
  it("详情端点行对象原样返回，不做 unwrap", async () => {
    const row = { id: 1, login: "boss", counts: { likes: 3 } };
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(JSON.stringify(row), { status: 200 }),
    );
    await expect(dataProvider.getOne({ resource: "users", id: 1 })).resolves.toEqual({ data: row });
    expect(fetch).toHaveBeenCalledWith(
      "/api/admin/users/1",
      expect.objectContaining({ credentials: "include" }),
    );
  });
});

describe("dataProvider.getMany · 逐 id 汇总", () => {
  it("按 id 逐个取行，返回 {data: 行数组}", async () => {
    const fetchSpy = vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
      const url = String(input);
      const id = url.endsWith("/1") ? 1 : 2;
      return new Response(JSON.stringify(rows[id - 1]), { status: 200 });
    });
    await expect(dataProvider.getMany!({ resource: "users", ids: [1, 2] })).resolves.toEqual({
      data: rows,
    });
    expect(fetchSpy).toHaveBeenCalledTimes(2);
    expect(fetchSpy).toHaveBeenCalledWith(
      "/api/admin/users/1",
      expect.objectContaining({ credentials: "include" }),
    );
    expect(fetchSpy).toHaveBeenCalledWith(
      "/api/admin/users/2",
      expect.objectContaining({ credentials: "include" }),
    );
  });
});
