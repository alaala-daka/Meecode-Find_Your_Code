import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { ConfigPage } from "./ConfigPage";

const CONFIG = {
  data: [
    { key: "online_window_minutes", value: "5", version: 1,
      updated_at: 0, updated_by: "system" },
    { key: "GITHUB_CLIENT_SECRET", value: "***", version: 3,
      updated_at: 0, updated_by: "boss" },
  ],
  total: 2,
};

const setupFetch = () => {
  const calls: { url: string; method: string; body?: { key?: string; value?: string; version?: number } }[] = [];
  vi.spyOn(globalThis, "fetch").mockImplementation(async (input, init) => {
    const url = String(input);
    const method = (init?.method ?? "GET").toUpperCase();
    calls.push({ url, method, body: init?.body ? JSON.parse(String(init.body)) : undefined });
    return new Response(JSON.stringify(CONFIG), { status: 200 });
  });
  return calls;
};

afterEach(() => vi.restoreAllMocks());

describe("ConfigPage", () => {
  it("脱敏值只读并提示", async () => {
    setupFetch();
    render(<ConfigPage />);
    expect(await screen.findByText("GITHUB_CLIENT_SECRET")).toBeInTheDocument();
    expect(screen.getByText("***")).toBeInTheDocument();
    expect(screen.getByText("密钥字段不可经界面修改")).toBeInTheDocument();
  });

  it("保存走 ConfirmDialog 且 PATCH 带 version", async () => {
    const calls = setupFetch();
    render(<ConfigPage />);
    await screen.findByText("online_window_minutes");
    fireEvent.change(screen.getByRole("textbox", { name: "online_window_minutes 值" }),
      { target: { value: "10" } });
    fireEvent.click(screen.getByRole("button", { name: "online_window_minutes 保存" }));
    fireEvent.click(screen.getByRole("button", { name: "确认" }));
    await waitFor(() => expect(calls.some(
      (c) => c.method === "PATCH" && c.body?.key === "online_window_minutes" &&
        c.body?.value === "10" && c.body?.version === 1)).toBe(true));
  });

  it("409 版本冲突：弹窗保留并展示 detail", async () => {
    vi.spyOn(globalThis, "fetch").mockImplementation(async (_input, init) => {
      const method = (init?.method ?? "GET").toUpperCase();
      if (method === "PATCH") {
        return new Response(
          JSON.stringify({ detail: "配置已被他人修改，请刷新重试" }),
          { status: 409 },
        );
      }
      return new Response(JSON.stringify(CONFIG), { status: 200 });
    });
    render(<ConfigPage />);
    await screen.findByText("online_window_minutes");
    fireEvent.change(screen.getByRole("textbox", { name: "online_window_minutes 值" }),
      { target: { value: "10" } });
    fireEvent.click(screen.getByRole("button", { name: "online_window_minutes 保存" }));
    fireEvent.click(screen.getByRole("button", { name: "确认" }));
    expect(await screen.findByText("配置已被他人修改，请刷新重试")).toBeInTheDocument();
    expect(screen.getByText("确认修改")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "确认" })).toBeInTheDocument();
  });
});
