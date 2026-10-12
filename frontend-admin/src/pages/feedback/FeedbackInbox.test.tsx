// src/pages/feedback/FeedbackInbox.test.tsx —— 收件箱：列表渲染/筛选/空态
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter } from "react-router";
import { afterEach, describe, expect, it, vi } from "vitest";

import { FeedbackInbox } from "./FeedbackInbox";

const ROWS = {
  data: [
    { id: 3, user_id: 7, user_login: "bob", category: "suggest", body: "希望支持排序",
      status: "pending", note: "", reply_count: 0, created_at: 1700000000, updated_at: 1700000000 },
    { id: 2, user_id: 7, user_login: "alice", category: "bug", body: "窄屏错乱",
      status: "done", note: "已修", reply_count: 2, created_at: 1699000000, updated_at: 1699500000 },
  ],
  total: 2,
};

type Call = { url: string; method: string };
const setupFetch = () => {
  const calls: Call[] = [];
  vi.spyOn(globalThis, "fetch").mockImplementation(async (input, init) => {
    calls.push({ url: String(input), method: (init?.method ?? "GET").toUpperCase() });
    return new Response(JSON.stringify(ROWS), { status: 200 });
  });
  return calls;
};

const renderInbox = () =>
  render(<MemoryRouter><FeedbackInbox /></MemoryRouter>);

afterEach(() => vi.restoreAllMocks());

describe("FeedbackInbox", () => {
  it("渲染行、状态徽标与回复数", async () => {
    setupFetch();
    renderInbox();
    expect(await screen.findByText("希望支持排序")).toBeInTheDocument();
    const row = screen.getByText("希望支持排序").closest("tr");
    expect(within(row!).getByText("待处理")).toBeInTheDocument();
    expect(within(row!).getByText("bob")).toBeInTheDocument();
    const row2 = screen.getByText("窄屏错乱").closest("tr");
    expect(within(row2!).getByText("已处理")).toBeInTheDocument();
    expect(within(row2!).getByRole("link", { name: "查看" })).toHaveAttribute("href", "/feedback/show/2");
  });

  it("改筛选重置页并带查询参数", async () => {
    const calls = setupFetch();
    renderInbox();
    await screen.findByText("希望支持排序");
    fireEvent.change(screen.getByRole("textbox", { name: "内容关键词" }),
      { target: { value: "排序" } });
    fireEvent.click(screen.getByRole("button", { name: "筛选" }));
    await waitFor(() => expect(calls.some((c) => c.url.includes("q=%E6%8E%92%E5%BA%8F"))).toBe(true));
    expect(calls.some((c) => c.url.includes("page=1"))).toBe(true);
  });

  it("空态与失败态均渲染 colSpan 行", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(JSON.stringify({ data: [], total: 0 }), { status: 200 }));
    renderInbox();
    expect(await screen.findByText("暂无反馈。")).toBeInTheDocument();

    vi.spyOn(globalThis, "fetch").mockRejectedValue(new Error("boom"));
    renderInbox();
    expect(await screen.findByText("加载失败，请稍后重试。")).toBeInTheDocument();
  });

  it("内容关键词 maxLength=50（对齐服务端 q 上限，防 422 误报加载失败）", async () => {
    setupFetch();
    renderInbox();
    await screen.findByText("希望支持排序");
    expect(screen.getByRole("textbox", { name: "内容关键词" })).toHaveAttribute("maxlength", "50");
  });
});
