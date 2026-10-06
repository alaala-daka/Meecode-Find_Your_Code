import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { Refine } from "@refinedev/core";
import { MemoryRouter } from "react-router";
import { afterEach, describe, expect, it, vi } from "vitest";

import { dataProvider } from "@/providers/dataProvider";
import { RepoList } from "./RepoList";

const rows = [
  {
    id: 3,
    github_id: 100,
    full_name: "demo/p100",
    owner_login: "demo",
    language: "Python",
    stars: 5,
    source: "submitted",
    status: "published",
    category: "工具",
    quality: 8,
    tagline_zh: "卖点",
    impression_count: 1,
    repo_view_count: 2,
    published_at: 1700000000,
  },
  {
    id: 2,
    github_id: 99,
    full_name: "demo/p99",
    owner_login: "demo",
    language: "Go",
    stars: 1,
    source: "crawled",
    status: "delisted",
    category: "其他",
    quality: 3,
    tagline_zh: "",
    impression_count: 0,
    repo_view_count: 0,
    published_at: 1700000000,
  },
  {
    id: 1,
    github_id: 98,
    full_name: "demo/p98",
    owner_login: "demo",
    language: "Rust",
    stars: 0,
    source: "submitted",
    status: "pending_claim",
    category: "其他",
    quality: 5,
    tagline_zh: "占位",
    impression_count: 0,
    repo_view_count: 0,
    published_at: 0,
  },
];

type Call = { url: string; method: string; body: unknown };

const setupFetch = (fail?: { urlSuffix: string; status: number; detail: string }) => {
  const calls: Call[] = [];
  vi.spyOn(globalThis, "fetch").mockImplementation(async (input, init) => {
    const url = String(input);
    const method = (init?.method ?? "GET").toUpperCase();
    const body = init?.body ? JSON.parse(String(init.body)) : undefined;
    calls.push({ url, method, body });
    if (fail && method === "POST" && url.endsWith(fail.urlSuffix)) {
      return new Response(JSON.stringify({ detail: fail.detail }), { status: fail.status });
    }
    if (method === "GET") {
      return new Response(JSON.stringify({ data: rows, total: rows.length }), { status: 200 });
    }
    return new Response(JSON.stringify({ ok: true }), { status: 200 });
  });
  return calls;
};

const renderList = () =>
  render(
    <MemoryRouter initialEntries={["/repos"]}>
      <Refine
        dataProvider={dataProvider}
        resources={[{ name: "repos", list: "/repos" }]}
      >
        <RepoList />
      </Refine>
    </MemoryRouter>,
  );

const rowScope = (fullName: string) => {
  const tr = screen.getByText(fullName).closest("tr");
  if (!tr) throw new Error(`未找到行：${fullName}`);
  return within(tr);
};

afterEach(() => {
  vi.restoreAllMocks();
});

describe("RepoList · 行内状态按钮条件渲染", () => {
  it("published→仅下架；delisted→上架+恢复；pending_claim→仅上架", async () => {
    setupFetch();
    renderList();
    await screen.findByText("demo/p100");

    const published = rowScope("demo/p100");
    expect(published.getByRole("button", { name: "下架" })).toBeInTheDocument();
    expect(published.queryByRole("button", { name: "上架" })).toBeNull();
    expect(published.queryByRole("button", { name: "恢复" })).toBeNull();

    const delisted = rowScope("demo/p99");
    expect(delisted.getByRole("button", { name: "上架" })).toBeInTheDocument();
    expect(delisted.getByRole("button", { name: "恢复" })).toBeInTheDocument();
    expect(delisted.queryByRole("button", { name: "下架" })).toBeNull();

    const pending = rowScope("demo/p98");
    expect(pending.getByRole("button", { name: "上架" })).toBeInTheDocument();
    expect(pending.queryByRole("button", { name: "下架" })).toBeNull();
    expect(pending.queryByRole("button", { name: "恢复" })).toBeNull();
  });
});

describe("RepoList · 状态动作", () => {
  it("published 行下架 → 确认 → POST /api/admin/repos/3/delist（无 body）", async () => {
    const calls = setupFetch();
    renderList();
    await screen.findByText("demo/p100");

    await userEvent.click(rowScope("demo/p100").getByRole("button", { name: "下架" }));
    await userEvent.click(await screen.findByRole("button", { name: "确认" }));

    await waitFor(() => {
      expect(calls.some((c) => c.url === "/api/admin/repos/3/delist")).toBe(true);
    });
    const call = calls.find((c) => c.url === "/api/admin/repos/3/delist")!;
    expect(call.method).toBe("POST");
    expect(call.body).toBeUndefined();
  });

  it("delisted 恢复 / pending_claim 上架 → POST 精确 URL", async () => {
    const calls = setupFetch();
    renderList();
    await screen.findByText("demo/p99");

    await userEvent.click(rowScope("demo/p99").getByRole("button", { name: "恢复" }));
    await userEvent.click(await screen.findByRole("button", { name: "确认" }));
    await waitFor(() => {
      expect(calls.some((c) => c.url === "/api/admin/repos/2/restore")).toBe(true);
    });

    await userEvent.click(rowScope("demo/p98").getByRole("button", { name: "上架" }));
    await userEvent.click(await screen.findByRole("button", { name: "确认" }));
    await waitFor(() => {
      expect(calls.some((c) => c.url === "/api/admin/repos/1/publish")).toBe(true);
    });

    const restore = calls.find((c) => c.url === "/api/admin/repos/2/restore")!;
    expect(restore.method).toBe("POST");
    expect(restore.body).toBeUndefined();
    const publish = calls.find((c) => c.url === "/api/admin/repos/1/publish")!;
    expect(publish.method).toBe("POST");
    expect(publish.body).toBeUndefined();
  });

  it("非法状态转移 409 → 页面 actionError 展示 detail", async () => {
    setupFetch({
      urlSuffix: "/repos/3/delist",
      status: 409,
      detail: "非法状态转移: published -> delist",
    });
    renderList();
    await screen.findByText("demo/p100");

    await userEvent.click(rowScope("demo/p100").getByRole("button", { name: "下架" }));
    await userEvent.click(await screen.findByRole("button", { name: "确认" }));

    expect(await screen.findByText(/非法状态转移/)).toBeInTheDocument();
    expect(screen.getByText(/下架失败/)).toBeInTheDocument();
  });
});

describe("RepoList · 元数据编辑", () => {
  it("编辑 → 确认 → PATCH /api/admin/repos/3 body {category, quality, tagline_zh}", async () => {
    const calls = setupFetch();
    renderList();
    await screen.findByText("demo/p100");

    await userEvent.click(rowScope("demo/p100").getByRole("button", { name: "编辑" }));

    await userEvent.click(await screen.findByRole("combobox", { name: "分类" }));
    await userEvent.click(await screen.findByRole("option", { name: "开发工具" }));

    const quality = screen.getByLabelText("质量");
    await userEvent.clear(quality);
    await userEvent.type(quality, "9");

    const tagline = screen.getByLabelText("卖点");
    await userEvent.clear(tagline);
    await userEvent.type(tagline, "新卖点");

    await userEvent.click(screen.getByRole("button", { name: "保存" }));
    await userEvent.click(await screen.findByRole("button", { name: "确认" }));

    await waitFor(() => {
      expect(calls.some((c) => c.method === "PATCH")).toBe(true);
    });
    const patch = calls.find((c) => c.method === "PATCH")!;
    expect(patch.url).toBe("/api/admin/repos/3");
    expect(patch.body).toEqual({ category: "开发工具", quality: 9, tagline_zh: "新卖点" });
  });
});

describe("RepoList · 筛选与搜索", () => {
  it("搜索 q + 状态筛选 → GET /api/admin/repos?q=&status=", async () => {
    const calls = setupFetch();
    renderList();
    await screen.findByText("demo/p100");

    await userEvent.type(screen.getByLabelText("仓库名搜索"), "demo/p");
    await userEvent.click(screen.getByRole("button", { name: "搜索" }));
    await waitFor(() => {
      expect(calls.some((c) => c.method === "GET" && c.url.includes("q=demo"))).toBe(true);
    });

    await userEvent.click(screen.getByRole("combobox", { name: "状态筛选" }));
    await userEvent.click(await screen.findByRole("option", { name: "delisted" }));
    await waitFor(() => {
      expect(
        calls.some((c) => c.method === "GET" && c.url.includes("status=delisted")),
      ).toBe(true);
    });
  });
});
