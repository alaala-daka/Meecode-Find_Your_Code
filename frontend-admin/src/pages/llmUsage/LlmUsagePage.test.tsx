import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
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
    await screen.findByText("模型分布");
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
    await screen.findByText("失败率");
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
  });
});
