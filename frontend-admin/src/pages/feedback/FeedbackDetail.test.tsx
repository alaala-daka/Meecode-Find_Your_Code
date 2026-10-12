// src/pages/feedback/FeedbackDetail.test.tsx —— 详情：状态流转/备注/回复均走 PATCH 与 POST
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router";
import { afterEach, describe, expect, it, vi } from "vitest";

import { FeedbackDetail } from "./FeedbackDetail";

const DETAIL = {
  id: 5, user_id: 7, user_login: "alice", category: "bug",
  body: "窄屏文件树错乱 <script>x</script>", contact: "a@b.c",
  status: "pending", note: "", created_at: 1700000000, updated_at: 1700000000,
  replies: [{ id: 1, body: "已收到", author_login: "boss",
    created_at: 1700001000, read_at: null }],
};

type Call = { url: string; method: string; body: unknown };
const setupFetch = () => {
  const calls: Call[] = [];
  vi.spyOn(globalThis, "fetch").mockImplementation(async (input, init) => {
    calls.push({
      url: String(input),
      method: (init?.method ?? "GET").toUpperCase(),
      body: init?.body ? JSON.parse(String(init.body)) : undefined,
    });
    return new Response(JSON.stringify(DETAIL), { status: 200 });
  });
  return calls;
};

const renderDetail = () =>
  render(
    <MemoryRouter initialEntries={["/feedback/show/5"]}>
      <Routes><Route path="/feedback/show/:id" element={<FeedbackDetail />} /></Routes>
    </MemoryRouter>,
  );

afterEach(() => vi.restoreAllMocks());

describe("FeedbackDetail", () => {
  it("渲染原文（纯文本）、联系方式与未读回复标", async () => {
    setupFetch();
    renderDetail();
    expect(await screen.findByText("窄屏文件树错乱 <script>x</script>")).toBeInTheDocument();
    expect(screen.getByText("a@b.c")).toBeInTheDocument();
    expect(screen.getByText("未读")).toBeInTheDocument();
    expect(screen.getByText("已收到")).toBeInTheDocument();
  });

  it("保存状态走 PATCH 并写审计链", async () => {
    const calls = setupFetch();
    renderDetail();
    await screen.findByText("窄屏文件树错乱 <script>x</script>");
    // radix Select 不是原生 <select>，fireEvent.change 改不动受控值——照 UserShow.test.tsx:55-58 的点选流
    await userEvent.click(screen.getByRole("combobox", { name: "状态" }));
    await userEvent.click(await screen.findByRole("option", { name: "已处理" }));
    await userEvent.click(screen.getByRole("button", { name: "保存状态" }));
    await userEvent.click(await screen.findByRole("button", { name: "确认" }));
    await waitFor(() => expect(calls.some((c) => c.method === "PATCH")).toBe(true));
    expect(calls.find((c) => c.method === "PATCH")?.body).toEqual({ status: "done" });
  });

  it("保存备注与发送回复走各自端点", async () => {
    const calls = setupFetch();
    renderDetail();
    await screen.findByText("窄屏文件树错乱 <script>x</script>");
    fireEvent.change(screen.getByLabelText("内部备注"), { target: { value: "已排期" } });
    fireEvent.click(screen.getByRole("button", { name: "保存备注" }));
    fireEvent.click(await screen.findByRole("button", { name: "确认" }));
    // run() 保存成功后异步收尾（关弹窗/清回复框/重载）——等页面回到就绪再输入回复
    await screen.findByRole("button", { name: "发送回复" });
    fireEvent.change(screen.getByLabelText("回复内容"), { target: { value: "已修复" } });
    fireEvent.click(screen.getByRole("button", { name: "发送回复" }));
    fireEvent.click(await screen.findByRole("button", { name: "确认" }));
    await waitFor(() => expect(calls.some((c) => c.method === "POST"
      && c.url === "/api/admin/feedback/5/replies")).toBe(true));
    expect(calls.find((c) => c.url.endsWith("/replies"))?.body).toEqual({ body: "已修复" });
  });

  it("加载失败展示内联错误", async () => {
    vi.spyOn(globalThis, "fetch").mockRejectedValue(new Error("boom"));
    renderDetail();
    expect(await screen.findByText("反馈加载失败，请稍后重试。")).toBeInTheDocument();
  });
});
