import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { Refine } from "@refinedev/core";
import { MemoryRouter } from "react-router";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { CommentRow, CommentStats } from "@/api/comments";
import { dataProvider } from "@/providers/dataProvider";
import { CommentList } from "./CommentList";

const rows: CommentRow[] = [
  {
    id: 7,
    repo_id: 3,
    repo_full_name: "demo/c81",
    user_id: 9,
    user_login: "u81",
    parent_id: null,
    content: "评论内容 A",
    status: "visible",
    moderation_reason: "疑似广告",
    screened: 1,
    created_at: 1700000000,
  },
  {
    id: 8,
    repo_id: 3,
    repo_full_name: "demo/c81",
    user_id: 10,
    user_login: "u82",
    parent_id: 7,
    content: "评论内容 B",
    status: "pending",
    moderation_reason: null,
    screened: 0,
    created_at: 1700000100,
  },
  {
    id: 9,
    repo_id: 4,
    repo_full_name: "demo/c82",
    user_id: 11,
    user_login: "u83",
    parent_id: null,
    content: "评论内容 C",
    status: "hidden",
    moderation_reason: "违规",
    screened: 1,
    created_at: 1700000200,
  },
  {
    id: 10,
    repo_id: 4,
    repo_full_name: "demo/c82",
    user_id: 12,
    user_login: "u84",
    parent_id: null,
    content: "评论内容 D",
    status: "deleted",
    moderation_reason: null,
    screened: 1,
    created_at: 1700000300,
  },
  {
    id: 11,
    repo_id: 5,
    repo_full_name: "demo/c83",
    user_id: 13,
    user_login: "u85",
    parent_id: null,
    content: "<img src=x onerror=alert(1)>",
    status: "visible",
    moderation_reason: null,
    screened: 1,
    created_at: 1700000400,
  },
];

type Call = { url: string; method: string; body: unknown };

type SetupOptions = {
  fail?: { urlSuffix: string; status: number; detail: string; method?: string };
  stats?: CommentStats;
  bulkResponse?: { ok: boolean; affected: number; not_found: number[]; skipped: number[] };
};

const setupFetch = (options: SetupOptions = {}) => {
  const calls: Call[] = [];
  const db = rows.map((r) => ({ ...r }));
  vi.spyOn(globalThis, "fetch").mockImplementation(async (input, init) => {
    const url = String(input);
    const method = (init?.method ?? "GET").toUpperCase();
    const body = init?.body ? JSON.parse(String(init.body)) : undefined;
    calls.push({ url, method, body });
    if (options.fail && method === (options.fail.method ?? "POST") && url.endsWith(options.fail.urlSuffix)) {
      return new Response(JSON.stringify({ detail: options.fail.detail }), { status: options.fail.status });
    }
    if (method === "GET" && url.startsWith("/api/admin/comments/stats")) {
      return new Response(
        JSON.stringify(options.stats ?? { pending: 1, visible: 2, hidden: 1, deleted: 1 }),
        { status: 200 },
      );
    }
    if (method === "GET") {
      return new Response(JSON.stringify({ data: db.map((r) => ({ ...r })), total: db.length }), {
        status: 200,
      });
    }
    if (method === "POST" && url.endsWith("/comments/bulk")) {
      return new Response(
        JSON.stringify(options.bulkResponse ?? { ok: true, affected: 0, not_found: [], skipped: [] }),
        { status: 200 },
      );
    }
    const hide = url.match(/\/comments\/(\d+)\/hide$/);
    if (method === "POST" && hide) {
      const row = db.find((r) => r.id === Number(hide[1]));
      if (row) row.status = "hidden";
      return new Response(JSON.stringify({ ok: true, status: "hidden" }), { status: 200 });
    }
    const restore = url.match(/\/comments\/(\d+)\/restore$/);
    if (method === "POST" && restore) {
      const row = db.find((r) => r.id === Number(restore[1]));
      if (row) row.status = "visible";
      return new Response(JSON.stringify({ ok: true, status: "visible" }), { status: 200 });
    }
    const remove = url.match(/\/comments\/(\d+)$/);
    if (method === "DELETE" && remove) {
      const row = db.find((r) => r.id === Number(remove[1]));
      if (row) row.status = "deleted";
      return new Response(JSON.stringify({ ok: true, status: "deleted" }), { status: 200 });
    }
    return new Response(JSON.stringify({ ok: true }), { status: 200 });
  });
  return calls;
};

const renderList = () =>
  render(
    <MemoryRouter initialEntries={["/comments"]}>
      <Refine dataProvider={dataProvider} resources={[{ name: "comments", list: "/comments" }]}>
        <CommentList />
      </Refine>
    </MemoryRouter>,
  );

const rowScope = (content: string) => {
  const tr = screen.getByText(content).closest("tr");
  if (!tr) throw new Error(`未找到行：${content}`);
  return within(tr);
};

afterEach(() => {
  vi.restoreAllMocks();
});

describe("CommentList · stats 徽章行", () => {
  it("stats 接口数据渲染为 4 个计数徽章", async () => {
    setupFetch({ stats: { pending: 2, visible: 5, hidden: 1, deleted: 3 } });
    renderList();
    await screen.findByText("评论内容 A");

    expect(await screen.findByText("待审 2")).toBeInTheDocument();
    expect(screen.getByText("可见 5")).toBeInTheDocument();
    expect(screen.getByText("隐藏 1")).toBeInTheDocument();
    expect(screen.getByText("已删除 3")).toBeInTheDocument();
  });
});

describe("CommentList · 行操作按钮条件渲染（状态机）", () => {
  it("visible|pending→隐藏+删除；hidden→恢复+删除；deleted→无按钮", async () => {
    setupFetch();
    renderList();
    await screen.findByText("评论内容 A");

    const visible = rowScope("评论内容 A");
    expect(visible.getByRole("button", { name: "隐藏" })).toBeInTheDocument();
    expect(visible.getByRole("button", { name: "删除" })).toBeInTheDocument();
    expect(visible.queryByRole("button", { name: "恢复" })).toBeNull();
    expect(visible.getByRole("checkbox", { name: "选择评论 7" })).toBeInTheDocument();

    const pending = rowScope("评论内容 B");
    expect(pending.getByRole("button", { name: "隐藏" })).toBeInTheDocument();
    expect(pending.getByRole("button", { name: "删除" })).toBeInTheDocument();
    expect(pending.queryByRole("button", { name: "恢复" })).toBeNull();
    expect(pending.getByRole("checkbox", { name: "选择评论 8" })).toBeInTheDocument();

    const hidden = rowScope("评论内容 C");
    expect(hidden.getByRole("button", { name: "恢复" })).toBeInTheDocument();
    expect(hidden.getByRole("button", { name: "删除" })).toBeInTheDocument();
    expect(hidden.queryByRole("button", { name: "隐藏" })).toBeNull();
    expect(hidden.queryByRole("checkbox")).toBeNull();

    const deleted = rowScope("评论内容 D");
    expect(deleted.queryByRole("button")).toBeNull();
    expect(deleted.queryByRole("checkbox")).toBeNull();
    expect(deleted.getByText("deleted")).toBeInTheDocument();
  });
});

describe("CommentList · 行操作", () => {
  it("删除 → 确认 → DELETE /api/admin/comments/7 → refetch 后徽章 deleted 且按钮消失", async () => {
    const calls = setupFetch();
    renderList();
    await screen.findByText("评论内容 A");

    await userEvent.click(rowScope("评论内容 A").getByRole("button", { name: "删除" }));
    await userEvent.click(await screen.findByRole("button", { name: "确认" }));

    await waitFor(() => {
      expect(calls.some((c) => c.method === "DELETE" && c.url === "/api/admin/comments/7")).toBe(true);
    });
    await waitFor(() => {
      expect(rowScope("评论内容 A").getByText("deleted")).toBeInTheDocument();
    });
    expect(rowScope("评论内容 A").queryByRole("button")).toBeNull();
    expect(rowScope("评论内容 A").queryByRole("checkbox")).toBeNull();
  });

  it("隐藏 / 恢复 → POST 精确 URL（无 body）", async () => {
    const calls = setupFetch();
    renderList();
    await screen.findByText("评论内容 B");

    await userEvent.click(rowScope("评论内容 B").getByRole("button", { name: "隐藏" }));
    await userEvent.click(await screen.findByRole("button", { name: "确认" }));
    await waitFor(() => {
      expect(calls.some((c) => c.url === "/api/admin/comments/8/hide")).toBe(true);
    });

    await userEvent.click(rowScope("评论内容 C").getByRole("button", { name: "恢复" }));
    await userEvent.click(await screen.findByRole("button", { name: "确认" }));
    await waitFor(() => {
      expect(calls.some((c) => c.url === "/api/admin/comments/9/restore")).toBe(true);
    });

    const hide = calls.find((c) => c.url === "/api/admin/comments/8/hide")!;
    expect(hide.method).toBe("POST");
    expect(hide.body).toBeUndefined();
    const restore = calls.find((c) => c.url === "/api/admin/comments/9/restore")!;
    expect(restore.method).toBe("POST");
    expect(restore.body).toBeUndefined();
  });

  it("非法状态转移 409 → 错误浮现在确认弹窗内部且弹窗保持打开", async () => {
    setupFetch({
      fail: {
        urlSuffix: "/comments/7/hide",
        status: 409,
        detail: "非法状态转移: visible -> hide",
      },
    });
    renderList();
    await screen.findByText("评论内容 A");

    await userEvent.click(rowScope("评论内容 A").getByRole("button", { name: "隐藏" }));
    const dialog = await screen.findByRole("dialog", { name: "确认隐藏" });
    await userEvent.click(within(dialog).getByRole("button", { name: "确认" }));

    const errorNode = await within(dialog).findByRole("alert");
    expect(errorNode).toHaveTextContent("隐藏失败：非法状态转移: visible -> hide");
    expect(dialog).toContainElement(errorNode);
    expect(within(dialog).getByRole("button", { name: "确认" })).toBeInTheDocument();
  });
});

describe("CommentList · 批量隐藏", () => {
  it("多选提交 {ids:[...], action:'hide'} + affected/not_found/skipped 结果就地反馈", async () => {
    const calls = setupFetch({
      bulkResponse: { ok: true, affected: 1, not_found: [99], skipped: [5] },
    });
    renderList();
    await screen.findByText("评论内容 A");

    await userEvent.click(screen.getByRole("checkbox", { name: "选择评论 7" }));
    await userEvent.click(screen.getByRole("checkbox", { name: "选择评论 8" }));
    await userEvent.click(screen.getByRole("button", { name: "批量隐藏" }));
    const dialog = await screen.findByRole("dialog", { name: "确认批量隐藏" });
    await userEvent.click(within(dialog).getByRole("button", { name: "确认" }));

    await waitFor(() => {
      expect(calls.some((c) => c.url === "/api/admin/comments/bulk")).toBe(true);
    });
    const bulk = calls.find((c) => c.url === "/api/admin/comments/bulk")!;
    expect(bulk.method).toBe("POST");
    expect(bulk.body).toEqual({ ids: [7, 8], action: "hide" });

    const summary = await screen.findByText(/批量隐藏完成/);
    expect(summary).toHaveTextContent("已隐藏 1 条");
    expect(summary).toHaveTextContent("未找到 1 条");
    expect(summary).toHaveTextContent("跳过 1 条");
    expect(summary).toHaveTextContent("99");
    expect(summary).toHaveTextContent("5");
    expect(screen.getByRole("checkbox", { name: "选择评论 7" })).not.toBeChecked();
    expect(screen.getByRole("checkbox", { name: "选择评论 8" })).not.toBeChecked();
  });

  it("批量隐藏失败 409 → 错误浮现在批量确认弹窗内部", async () => {
    setupFetch({
      fail: { urlSuffix: "/comments/bulk", status: 409, detail: "非法状态转移: visible -> hide" },
    });
    renderList();
    await screen.findByText("评论内容 A");

    await userEvent.click(screen.getByRole("checkbox", { name: "选择评论 7" }));
    await userEvent.click(screen.getByRole("button", { name: "批量隐藏" }));
    const dialog = await screen.findByRole("dialog", { name: "确认批量隐藏" });
    await userEvent.click(within(dialog).getByRole("button", { name: "确认" }));

    const errorNode = await within(dialog).findByRole("alert");
    expect(errorNode).toHaveTextContent("批量隐藏失败：非法状态转移: visible -> hide");
    expect(dialog).toContainElement(errorNode);
  });
});

describe("CommentList · UGC 纯文本（F8）", () => {
  it("content 中的 HTML 以纯文本渲染，不注入 DOM", async () => {
    setupFetch();
    const { container } = renderList();
    await screen.findByText("<img src=x onerror=alert(1)>");

    expect(container.querySelector("img")).toBeNull();
  });
});

describe("CommentList · 筛选", () => {
  it("状态选择 + 仓库 ID → GET /api/admin/comments?status=&repo_id=", async () => {
    const calls = setupFetch();
    renderList();
    await screen.findByText("评论内容 A");

    await userEvent.click(screen.getByRole("combobox", { name: "状态筛选" }));
    await userEvent.click(await screen.findByRole("option", { name: "hidden" }));
    await waitFor(() => {
      expect(calls.some((c) => c.method === "GET" && c.url.includes("status=hidden"))).toBe(true);
    });

    await userEvent.type(screen.getByLabelText("仓库 ID"), "3");
    await userEvent.click(screen.getByRole("button", { name: "筛选" }));
    await waitFor(() => {
      expect(calls.some((c) => c.method === "GET" && c.url.includes("repo_id=3"))).toBe(true);
    });
  });
});
