import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { AuditLogPage } from "./AuditLogPage";

const ROWS = {
  data: [
    { id: 2, ts: "2026-10-09T08:00:00Z", admin_login: "boss", action: "api_policy.update",
      target_type: "api_policy", target_id: "llm", detail: { enabled: false } },
    { id: 1, ts: "2026-10-09T07:00:00Z", admin_login: "boss", action: "user.ban",
      target_type: "user", target_id: "7", detail: null },
  ],
  total: 2,
};

const setupFetch = () => {
  const calls: { url: string }[] = [];
  vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
    const url = String(input);
    calls.push({ url });
    return new Response(JSON.stringify(ROWS), { status: 200 });
  });
  return calls;
};

afterEach(() => vi.restoreAllMocks());

describe("AuditLogPage", () => {
  it("渲染审计行，detail 纯文本等宽，空 detail 显示 —", async () => {
    setupFetch();
    render(<AuditLogPage />);
    expect(await screen.findByText("api_policy.update")).toBeInTheDocument();
    expect(screen.getByText("user.ban")).toBeInTheDocument();
    expect(screen.getByText(/"enabled": false/)).toBeInTheDocument();
    expect(screen.getByText("—")).toBeInTheDocument();
  });

  it("按 action 筛选触发带参请求", async () => {
    const calls = setupFetch();
    render(<AuditLogPage />);
    await screen.findByText("user.ban");
    fireEvent.change(screen.getByRole("textbox", { name: "动作" }),
      { target: { value: "user.ban" } });
    fireEvent.click(screen.getByRole("button", { name: "查询" }));
    await waitFor(() => expect(
      calls.some((c) => c.url.includes("action=user.ban"))).toBe(true));
  });
});
