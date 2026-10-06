import { render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { DashboardPage } from "./DashboardPage";

type Call = {
  url: string;
  method: string;
  credentials?: RequestCredentials;
  body: unknown;
};

const setupFetch = (payload: Record<string, unknown>) => {
  const calls: Call[] = [];
  vi.spyOn(globalThis, "fetch").mockImplementation(async (input, init) => {
    calls.push({
      url: String(input),
      method: (init?.method ?? "GET").toUpperCase(),
      credentials: init?.credentials,
      body: init?.body ? JSON.parse(String(init.body)) : undefined,
    });
    return new Response(JSON.stringify(payload), { status: 200 });
  });
  return calls;
};

const cardScope = (label: string) => {
  const card = screen.getByText(label).closest<HTMLDivElement>("div.rounded-lg");
  if (!card) throw new Error(`未找到卡片：${label}`);
  return within(card);
};

const FULL = {
  total_users: 42,
  new_users_today: 3,
  total_repos: 17,
  published_repos: 12,
  delisted_repos: 2,
  pending_comments: 5,
};

const LIVE_LABELS = ["注册总数", "今日新增", "仓库总数", "已上架", "已下架", "待审评论"] as const;

afterEach(() => {
  vi.restoreAllMocks();
});

describe("DashboardPage · 概览卡数值渲染", () => {
  it("overview 6 项计数渲染到对应卡片，数值 font-mono", async () => {
    setupFetch(FULL);
    render(<DashboardPage />);

    const value = await cardScope("注册总数").findByText("42");
    expect(value).toHaveClass("font-mono");
    expect(cardScope("今日新增").getByText("3")).toBeInTheDocument();
    expect(cardScope("仓库总数").getByText("17")).toBeInTheDocument();
    expect(cardScope("已上架").getByText("12")).toBeInTheDocument();
    expect(cardScope("已下架").getByText("2")).toBeInTheDocument();
    expect(cardScope("待审评论").getByText("5")).toBeInTheDocument();
  });
});

describe("DashboardPage · 空数据容错", () => {
  it("overview 缺字段 → 对应卡显示 `—`，已给字段照常渲染", async () => {
    setupFetch({ total_users: 42 });
    render(<DashboardPage />);

    expect(await cardScope("注册总数").findByText("42")).toBeInTheDocument();
    for (const label of LIVE_LABELS) {
      if (label === "注册总数") continue;
      expect(cardScope(label).getByText("—")).toBeInTheDocument();
    }
  });

  it("字段为 0 显示 0（不回退 `—`），缺键才显示 `—`", async () => {
    setupFetch({ new_users_today: 0 });
    render(<DashboardPage />);

    expect(await cardScope("今日新增").findByText("0")).toBeInTheDocument();
    expect(cardScope("注册总数").getByText("—")).toBeInTheDocument();
  });
});

describe("DashboardPage · 卡片构成", () => {
  it("共 8 张卡（6 实况 + 2 灰态占位带「二期」徽章），全部静置无影", async () => {
    setupFetch(FULL);
    const { container } = render(<DashboardPage />);
    await cardScope("注册总数").findByText("42");

    expect(screen.getAllByText("二期")).toHaveLength(2);
    for (const label of ["本年累计访问", "当前在线"] as const) {
      const card = cardScope(label);
      expect(card.getByText("—")).toBeInTheDocument();
      expect(card.getByText("二期")).toBeInTheDocument();
    }

    const cards = container.querySelectorAll("div.rounded-lg");
    expect(cards).toHaveLength(8);
    for (const card of cards) {
      expect(card.classList.contains("shadow")).toBe(false);
    }
  });
});

describe("DashboardPage · 数据拉取", () => {
  it("仅一次 GET /api/admin/overview（credentials include，无 body）", async () => {
    const calls = setupFetch(FULL);
    render(<DashboardPage />);
    await cardScope("注册总数").findByText("42");

    expect(calls).toHaveLength(1);
    expect(calls[0].url).toBe("/api/admin/overview");
    expect(calls[0].method).toBe("GET");
    expect(calls[0].credentials).toBe("include");
    expect(calls[0].body).toBeUndefined();
  });
});

describe("DashboardPage · 二期字段红线", () => {
  it("mock 混入二期字段也不渲染数值，占位卡恒显 `—`", async () => {
    setupFetch({ ...FULL, today_pv: 9999, year_visits: 88888, online: 77 });
    render(<DashboardPage />);

    expect(await cardScope("注册总数").findByText("42")).toBeInTheDocument();
    for (const leaked of ["9999", "88888", "77"]) {
      expect(screen.queryByText(leaked)).toBeNull();
    }
    for (const label of ["本年累计访问", "当前在线"] as const) {
      expect(cardScope(label).getByText("—")).toBeInTheDocument();
    }
  });
});
