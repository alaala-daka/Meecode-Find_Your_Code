import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { Refine } from "@refinedev/core";
import { MemoryRouter, Route, Routes } from "react-router";
import { afterEach, describe, expect, it, vi } from "vitest";

import { dataProvider } from "@/providers/dataProvider";
import { UserShow } from "./UserShow";

const detail = {
  id: 1,
  login: "alice",
  avatar_url: "https://example.com/a.png",
  created_at: 1700000000,
  ban_comment_until: 1700003600,
  ban_submit_until: null,
  ban_note: "刷屏",
  admin_note: "观察",
  status: "banned",
  counts: { likes: 1, favorites: 2, visits: 3, comments: 4 },
  recent_interactions: [{ created_at: 1700001000, kind: "visit", repo_id: 3 }],
};

type Call = { url: string; method: string; body: unknown };

const setupFetch = () => {
  const calls: Call[] = [];
  vi.spyOn(globalThis, "fetch").mockImplementation(async (input, init) => {
    const url = String(input);
    const method = (init?.method ?? "GET").toUpperCase();
    const body = init?.body ? JSON.parse(String(init.body)) : undefined;
    calls.push({ url, method, body });
    return new Response(JSON.stringify({ ok: true, ...detail }), { status: 200 });
  });
  return calls;
};

const renderShow = () =>
  render(
    <MemoryRouter initialEntries={["/users/show/1"]}>
      <Refine
        dataProvider={dataProvider}
        resources={[{ name: "users", list: "/users", show: "/users/show/:id" }]}
      >
        <Routes>
          <Route path="/users/show/:id" element={<UserShow />} />
        </Routes>
      </Refine>
    </MemoryRouter>,
  );

const pickDuration = async (label: string) => {
  await userEvent.click(screen.getByRole("combobox"));
  await userEvent.click(await screen.findByRole("option", { name: label }));
};

afterEach(() => {
  vi.restoreAllMocks();
});

describe("UserShow · 封禁面板", () => {
  it("勾选禁言 + 7天 → POST /users/1/ban {mute_comment:true, mute_submit:false, until:now+604800, note}", async () => {
    const calls = setupFetch();
    renderShow();
    await screen.findByText("alice");

    await userEvent.click(screen.getByRole("checkbox", { name: "禁言" }));
    await pickDuration("7天");
    await userEvent.type(screen.getByLabelText("处罚备注"), "刷屏");

    const t0 = Math.floor(Date.now() / 1000);
    await userEvent.click(screen.getByRole("button", { name: "封禁" }));
    await userEvent.click(await screen.findByRole("button", { name: "确认" }));
    await waitFor(() => {
      expect(calls.some((c) => c.url.endsWith("/users/1/ban"))).toBe(true);
    });
    const t1 = Math.floor(Date.now() / 1000);

    const ban = calls.find((c) => c.url.endsWith("/users/1/ban"))!;
    expect(ban.url).toBe("/api/admin/users/1/ban");
    expect(ban.method).toBe("POST");
    const body = ban.body as {
      mute_comment: boolean;
      mute_submit: boolean;
      until: number;
      note: string;
    };
    expect(body.mute_comment).toBe(true);
    expect(body.mute_submit).toBe(false);
    expect(body.note).toBe("刷屏");
    expect(body.until).toBeGreaterThanOrEqual(t0 + 604800);
    expect(body.until).toBeLessThanOrEqual(t1 + 604800);
  });

  it("禁言+禁投稿双开关 → body 两标志均为 true", async () => {
    const calls = setupFetch();
    renderShow();
    await screen.findByText("alice");

    await userEvent.click(screen.getByRole("checkbox", { name: "禁言" }));
    await userEvent.click(screen.getByRole("checkbox", { name: "禁投稿" }));
    await pickDuration("7天");
    await userEvent.click(screen.getByRole("button", { name: "封禁" }));
    await userEvent.click(await screen.findByRole("button", { name: "确认" }));
    await waitFor(() => {
      expect(calls.some((c) => c.url.endsWith("/users/1/ban"))).toBe(true);
    });

    const body = calls.find((c) => c.url.endsWith("/users/1/ban"))!.body as {
      mute_comment: boolean;
      mute_submit: boolean;
      note: string;
    };
    expect(body.mute_comment).toBe(true);
    expect(body.mute_submit).toBe(true);
    expect(typeof body.note).toBe("string");
  });

  it("时长永久 → until 固定 253402300799", async () => {
    const calls = setupFetch();
    renderShow();
    await screen.findByText("alice");

    await userEvent.click(screen.getByRole("checkbox", { name: "禁言" }));
    await pickDuration("永久");
    await userEvent.click(screen.getByRole("button", { name: "封禁" }));
    await userEvent.click(await screen.findByRole("button", { name: "确认" }));
    await waitFor(() => {
      expect(calls.some((c) => c.url.endsWith("/users/1/ban"))).toBe(true);
    });

    const body = calls.find((c) => c.url.endsWith("/users/1/ban"))!.body as { until: number };
    expect(body.until).toBe(253402300799);
  });

  it("解封按钮 → POST /users/1/unban", async () => {
    const calls = setupFetch();
    renderShow();
    await screen.findByText("alice");

    await userEvent.click(screen.getByRole("button", { name: "解封" }));
    await userEvent.click(await screen.findByRole("button", { name: "确认" }));
    await waitFor(() => {
      expect(calls.some((c) => c.url.endsWith("/users/1/unban"))).toBe(true);
    });

    const unban = calls.find((c) => c.url.endsWith("/users/1/unban"))!;
    expect(unban.url).toBe("/api/admin/users/1/unban");
    expect(unban.method).toBe("POST");
    expect(unban.body).toBeUndefined();
  });
});

describe("UserShow · 管理备注", () => {
  it("保存备注 → PATCH /api/admin/users/1 body {admin_note}", async () => {
    const calls = setupFetch();
    renderShow();
    await screen.findByText("alice");

    const input = screen.getByLabelText("管理备注");
    await userEvent.clear(input);
    await userEvent.type(input, "重点观察");
    await userEvent.click(screen.getByRole("button", { name: "保存备注" }));
    await userEvent.click(await screen.findByRole("button", { name: "确认" }));
    await waitFor(() => {
      expect(calls.some((c) => c.method === "PATCH")).toBe(true);
    });

    const patch = calls.find((c) => c.method === "PATCH")!;
    expect(patch.url).toBe("/api/admin/users/1");
    expect(patch.body).toEqual({ admin_note: "重点观察" });
  });
});
