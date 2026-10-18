import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { LlmUsagePage } from "./LlmUsagePage";

type Call = { url: string };

const DAILY = [
  { date: "2026-10-12", calls: 3, prompt_tokens: 100, completion_tokens: 50, errors: 1, avg_latency_ms: 200 },
  { date: "2026-10-13", calls: 0, prompt_tokens: 0, completion_tokens: 0, errors: 0, avg_latency_ms: 0 },
];

const STATS = {
  daily: DAILY,
  models: [{ model: "gpt-4o", calls: 3, tokens: 150 }],
  repos_top: [{ repo_id: 7, name: "a/b", calls: 2, tokens: 90 }],
};

const setupFetch = (payload: unknown = STATS) => {
  const calls: Call[] = [];
  vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
    calls.push({ url: String(input) });
    return new Response(JSON.stringify(payload), { status: 200 });
  });
  return calls;
};

const card = (label: string) =>
  screen.getByText(label).closest<HTMLDivElement>("div.rounded-lg")!;

afterEach(() => vi.restoreAllMocks());

describe("LlmUsagePage", () => {
  it("汇总卡按日汇总（失败率=errors/calls、均耗时按 calls 加权）", async () => {
    setupFetch();
    render(<LlmUsagePage />);
    await screen.findByText("gpt-4o");
    const callsCard = within(card("区间调用数"));
    expect(callsCard.getByText("3")).toBeInTheDocument();
    const tokensCard = within(card("tokens 合计"));
    expect(tokensCard.getByText("150")).toBeInTheDocument();
    const errCard = within(card("失败率"));
    expect(errCard.getByText("33.3%")).toBeInTheDocument();
    const latCard = within(card("平均耗时"));
    expect(latCard.getByText("200 ms")).toBeInTheDocument();
  });

  it("渲染双轴图与两张表", async () => {
    setupFetch();
    render(<LlmUsagePage />);
    await waitFor(() => expect(document.querySelector("svg")).not.toBeNull());
    expect(screen.getByText("gpt-4o")).toBeInTheDocument();
    expect(screen.getByText("a/b")).toBeInTheDocument();
    expect(screen.getByText("仓库 Top 10")).toBeInTheDocument();
  });

  it("区间按钮切换改写 from/to", async () => {
    const calls = setupFetch();
    render(<LlmUsagePage />);
    await screen.findByText("模型分布");
    const parseRange = (url: string) =>
      /llm\/stats\?from=(\d{4}-\d{2}-\d{2})&to=(\d{4}-\d{2}-\d{2})/.exec(url);
    const initialFrom = parseRange(calls[0].url)?.[1];
    expect(initialFrom).toMatch(/^\d{4}-\d{2}-\d{2}$/);
    const before = calls.length;
    fireEvent.click(screen.getByRole("button", { name: "近 30 日" }));
    await waitFor(() => {
      const hit = calls.slice(before).some((c) => {
        const m = parseRange(c.url);
        // 点击后新增请求：from ≠ 初次 from，且 from/to 为 30 日窗口（跨度 29 天）
        return (
          m !== null &&
          m[1] !== initialFrom &&
          Date.parse(m[2]) - Date.parse(m[1]) === 29 * 86_400_000
        );
      });
      expect(hit).toBe(true);
    });
  });

  it("零调用时失败率与均耗时显 —", async () => {
    setupFetch({ daily: [DAILY[1]], models: [], repos_top: [] });
    render(<LlmUsagePage />);
    await screen.findByText("暂无模型调用。");
    expect(within(card("区间调用数")).getByText("0")).toBeInTheDocument();
    expect(within(card("tokens 合计")).getByText("0")).toBeInTheDocument();
    expect(within(card("失败率")).getByText("—")).toBeInTheDocument();
    expect(within(card("平均耗时")).getByText("—")).toBeInTheDocument();
    expect(screen.getByText("暂无模型调用。")).toBeInTheDocument();
    expect(screen.getByText("暂无仓库消耗。")).toBeInTheDocument();
  });

  it("加载失败内联 role=alert（禁 Toast）", async () => {
    vi.spyOn(globalThis, "fetch").mockRejectedValue(new Error("离线"));
    render(<LlmUsagePage />);
    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("离线");
    expect(within(card("区间调用数")).getByText("—")).toBeInTheDocument();
    expect(within(card("tokens 合计")).getByText("—")).toBeInTheDocument();
    expect(screen.queryByText("暂无模型调用。")).not.toBeInTheDocument();
    expect(screen.queryByText("暂无仓库消耗。")).not.toBeInTheDocument();
    expect(screen.getAllByRole("cell", { name: "加载失败，请切换区间重试。" })).toHaveLength(2);
  });

  it("首次加载期间显示未知值和表格加载行", () => {
    vi.spyOn(globalThis, "fetch").mockReturnValue(new Promise<Response>(() => {}));
    render(<LlmUsagePage />);
    expect(within(card("区间调用数")).getByText("—")).toBeInTheDocument();
    expect(within(card("tokens 合计")).getByText("—")).toBeInTheDocument();
    expect(screen.getAllByRole("cell", { name: "加载中…" })).toHaveLength(2);
    expect(screen.queryByText("暂无模型调用。")).not.toBeInTheDocument();
  });

  it("新区间加载和失败时清除旧结果，并可切换到另一区间恢复", async () => {
    let rejectNext!: (reason: Error) => void;
    vi.spyOn(globalThis, "fetch")
      .mockResolvedValueOnce(new Response(JSON.stringify(STATS)))
      .mockImplementationOnce(() => new Promise<Response>((_resolve, reject) => { rejectNext = reject; }))
      .mockResolvedValueOnce(new Response(JSON.stringify({ daily: [DAILY[1]], models: [], repos_top: [] })));
    render(<LlmUsagePage />);
    await screen.findByText("gpt-4o");
    fireEvent.click(screen.getByRole("button", { name: "近 30 日" }));
    expect(within(card("区间调用数")).getByText("—")).toBeInTheDocument();
    expect(screen.queryByText("gpt-4o")).not.toBeInTheDocument();
    expect(screen.queryByText("a/b")).not.toBeInTheDocument();
    expect(document.querySelector(".recharts-wrapper")).toBeNull();
    expect(screen.getAllByRole("cell", { name: "加载中…" })).toHaveLength(2);
    await act(async () => { rejectNext(new Error("离线")); });
    expect(await screen.findByRole("alert")).toHaveTextContent("离线");
    expect(within(card("tokens 合计")).getByText("—")).toBeInTheDocument();
    expect(screen.queryByText("暂无模型调用。")).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "近 90 日" }));
    await screen.findByText("暂无模型调用。");
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    expect(within(card("区间调用数")).getByText("0")).toBeInTheDocument();
  });

  it("迟到的旧区间响应不覆盖当前结果", async () => {
    let resolveOld!: (response: Response) => void;
    vi.spyOn(globalThis, "fetch")
      .mockImplementationOnce(() => new Promise<Response>((resolve) => { resolveOld = resolve; }))
      .mockResolvedValueOnce(new Response(JSON.stringify({ daily: [DAILY[1]], models: [], repos_top: [] })));
    render(<LlmUsagePage />);
    fireEvent.click(screen.getByRole("button", { name: "近 30 日" }));
    await screen.findByText("暂无模型调用。");
    await act(async () => { resolveOld(new Response(JSON.stringify(STATS))); });
    expect(screen.queryByText("gpt-4o")).not.toBeInTheDocument();
    expect(within(card("区间调用数")).getByText("0")).toBeInTheDocument();
  });
});
