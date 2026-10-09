import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { ApiPoliciesPage } from "./ApiPoliciesPage";

const POLICIES = {
  data: [
    { route_key: "admin", enabled: true, limit_per_min: 300 },
    { route_key: "llm", enabled: true, limit_per_min: 20 },
  ],
  total: 2,
};
const STATS = {
  range: "7d",
  buckets: [
    { route_key: "llm", calls: 10, errors: 1, error_rate: 0.1 },
    { route_key: "admin", calls: 5, errors: 0, error_rate: 0 },
  ],
};

const setupFetch = () => {
  const calls: { url: string; method: string; body?: { limit_per_min?: number } }[] = [];
  vi.spyOn(globalThis, "fetch").mockImplementation(async (input, init) => {
    const url = String(input);
    const method = (init?.method ?? "GET").toUpperCase();
    calls.push({ url, method, body: init?.body ? JSON.parse(String(init.body)) : undefined });
    const payload = url.includes("api-stats") ? STATS : POLICIES;
    return new Response(JSON.stringify(payload), { status: 200 });
  });
  return calls;
};

afterEach(() => vi.restoreAllMocks());

describe("ApiPoliciesPage", () => {
  it("列表渲染桶名/调用量/错误率，保护桶开关禁用", async () => {
    setupFetch();
    render(<ApiPoliciesPage />);
    expect(await screen.findByText("llm")).toBeInTheDocument();
    expect(screen.getByText("admin")).toBeInTheDocument();
    expect(screen.getByText("10")).toBeInTheDocument();
    expect(screen.getByText("保护")).toBeInTheDocument();
    const stopButtons = screen.getAllByRole("button", { name: "停用" });
    expect(stopButtons.some((b) => (b as HTMLButtonElement).disabled)).toBe(true);
  });

  it("改限额走 ConfirmDialog，确认后 PATCH", async () => {
    const calls = setupFetch();
    render(<ApiPoliciesPage />);
    await screen.findByText("llm");
    fireEvent.change(screen.getByRole("spinbutton", { name: "llm 限额" }),
      { target: { value: "5" } });
    fireEvent.click(screen.getByRole("button", { name: "llm 保存" }));
    expect(screen.getByText("确认修改")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "确认" }));
    await waitFor(() => expect(calls.some(
      (c) => c.method === "PATCH" && c.url.includes("/api-policies/llm") &&
        c.body?.limit_per_min === 5)).toBe(true));
  });
});
