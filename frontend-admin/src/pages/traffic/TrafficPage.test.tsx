import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { TrafficPage } from "./TrafficPage";

type Call = { url: string };

const DAY = { date: "2026-10-09", pv: 12, uv: 5, new_users: 1,
               active_users: 3, api_calls: 80, errors: 1 };

const setupFetch = () => {
  const calls: Call[] = [];
  vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
    const url = String(input);
    calls.push({ url });
    let payload: unknown = { years: [{ year: 2026, pv: 100, uv_avg: 4 }] };
    if (url.includes("/traffic?range=year=")) {
      payload = {
        range: "year=2026",
        months: [{ month: "2026-01", pv: 10, uv_avg: 2, api_calls: 1,
                   errors: 0, new_users: 0 }],
        summary: { year: 2026, year_pv: 100, daily_pv_avg: 3.2, daily_uv_avg: 4.5,
                   new_users_year: 7, peak_day: { date: "2026-10-09", pv: 12 } },
      };
    } else if (url.includes("/traffic?range=")) {
      payload = { range: "7d", days: [DAY] };
    }
    return new Response(JSON.stringify(payload), { status: 200 });
  });
  return calls;
};

afterEach(() => vi.restoreAllMocks());

describe("TrafficPage", () => {
  it("默认拉 7d 并渲染图表", async () => {
    const calls = setupFetch();
    render(<TrafficPage />);
    await waitFor(() => expect(
      calls.some((c) => c.url.includes("range=7d"))).toBe(true));
    await waitFor(() => expect(document.querySelector("svg")).not.toBeNull());
  });

  it("切 30d 触发对应请求", async () => {
    const calls = setupFetch();
    render(<TrafficPage />);
    await waitFor(() => expect(calls.length).toBeGreaterThan(0));
    fireEvent.click(screen.getByRole("button", { name: "近 30 天" }));
    await waitFor(() => expect(
      calls.some((c) => c.url.includes("range=30d"))).toBe(true));
  });

  it("年度视图渲染汇总卡与峰值日", async () => {
    setupFetch();
    render(<TrafficPage />);
    await waitFor(() => expect(document.querySelector("svg")).not.toBeNull());
    fireEvent.click(screen.getByRole("button", { name: "年度" }));
    expect(await screen.findByText("年 PV 总量")).toBeInTheDocument();
    expect(screen.getByText("100")).toBeInTheDocument();
    expect(screen.getByText("2026-10-09（12）")).toBeInTheDocument();
  });

  it("年导航钳制 [2020, current+1]：到界后按钮 disabled 且不再发请求", async () => {
    const calls = setupFetch();
    render(<TrafficPage />);
    await waitFor(() => expect(document.querySelector("svg")).not.toBeNull());
    fireEvent.click(screen.getByRole("button", { name: "年度" }));
    expect(await screen.findByText("年 PV 总量")).toBeInTheDocument();

    const MIN_YEAR = 2020;
    const MAX_YEAR = new Date().getFullYear() + 1;
    const prev = screen.getByRole("button", { name: "‹" });
    const next = screen.getByRole("button", { name: "›" });

    for (let i = 0; i < 15; i += 1) fireEvent.click(prev);
    await waitFor(() => expect(prev).toBeDisabled());
    expect(screen.getByText(String(MIN_YEAR))).toBeInTheDocument();
    const callsAtMin = calls.length;
    fireEvent.click(prev);
    expect(calls.length).toBe(callsAtMin);

    for (let i = 0; i < 15; i += 1) fireEvent.click(next);
    await waitFor(() => expect(next).toBeDisabled());
    expect(screen.getByText(String(MAX_YEAR))).toBeInTheDocument();
    const callsAtMax = calls.length;
    fireEvent.click(next);
    expect(calls.length).toBe(callsAtMax);
  });
});
