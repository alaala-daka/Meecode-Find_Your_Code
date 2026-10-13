import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { LoginEventsPage } from "./LoginEventsPage";

const ROWS = {
  data: [
    { id: 3, ts: 1700000000, user_id: 7, login: "bob", ip_hash: "abcdef0123456789",
      event: "login", ok: 0 },
    { id: 2, ts: 1700000000, user_id: 7, login: "alice", ip_hash: "1234567890abcdef",
      event: "login", ok: 1 },
    { id: 1, ts: 1700000000, user_id: 7, login: "alice", ip_hash: "1234567890abcdef",
      event: "logout", ok: 1 },
  ],
  total: 3,
};

const setupFetch = (payload: unknown = ROWS) => {
  const calls: { url: string }[] = [];
  vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
    calls.push({ url: String(input) });
    return new Response(JSON.stringify(payload), { status: 200 });
  });
  return calls;
};

afterEach(() => vi.restoreAllMocks());

describe("LoginEventsPage", () => {
  it("列表渲染截断 ip_hash 与成败标记", async () => {
    setupFetch();
    render(<LoginEventsPage />);
    expect((await screen.findAllByText("alice")).length).toBeGreaterThan(0);
    expect(screen.getAllByText("abcdef012345").length).toBeGreaterThan(0);
    expect(screen.getByText("失败", { selector: "div" })).toBeInTheDocument();
  });

  it("筛选后带查询参数重查", async () => {
    const calls = setupFetch();
    render(<LoginEventsPage />);
    await screen.findAllByText("alice");
    fireEvent.change(screen.getByPlaceholderText("登录名模糊"),
      { target: { value: "bob" } });
    fireEvent.click(screen.getByRole("button", { name: "查询" }));
    await waitFor(() =>
      expect(calls.some((c) => c.url.includes("q=bob"))).toBe(true));
  });

  it("ip 反查弹窗提交后带 ip 参数", async () => {
    const calls = setupFetch();
    render(<LoginEventsPage />);
    await screen.findAllByText("alice");
    fireEvent.click(screen.getAllByRole("button", { name: "反查" })[0]);
    fireEvent.change(screen.getByRole("textbox", { name: "完整 IP" }),
      { target: { value: "9.9.9.9" } });
    fireEvent.click(screen.getByRole("button", { name: "反查提交" }));
    await waitFor(() =>
      expect(calls.some((c) => c.url.includes("ip=9.9.9.9"))).toBe(true));
  });
});
