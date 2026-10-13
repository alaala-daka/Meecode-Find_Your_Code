import { render, screen } from "@testing-library/react";
import { BrowserRouter } from "react-router";
import { afterEach, describe, expect, it, vi } from "vitest";

import { SearchPage } from "./SearchPage";

const PAYLOAD = {
  users: { count: 2, items: [{ id: 1, login: "alice", bio: "b" }] },
  repos: { count: 1001, items: [{ id: 2, name: "o/r", title: "t", description: "d" }] },
  comments: {
    count: 1,
    items: [{ id: 3, body: "c", author_login: "bob", repo_id: 9, hidden: true }],
  },
};

const withQ = (q: string) => {
  window.history.pushState({}, "", `/admin/search?q=${encodeURIComponent(q)}`);
};

afterEach(() => {
  vi.restoreAllMocks();
  window.history.pushState({}, "", "/admin/search");
});

describe("SearchPage", () => {
  it("渲染三组与 count 封顶文案", async () => {
    vi.spyOn(globalThis, "fetch").mockImplementation(async () =>
      new Response(JSON.stringify(PAYLOAD), { status: 200 }));
    withQ("关键词");
    render(
      <BrowserRouter basename="/admin">
        <SearchPage />
      </BrowserRouter>,
    );
    expect(await screen.findByText("alice")).toBeInTheDocument();
    expect(screen.getByText("1000+")).toBeInTheDocument();
    expect(screen.getByText("已隐藏")).toBeInTheDocument();
  });

  it("空词提示不请求", async () => {
    const spy = vi.spyOn(globalThis, "fetch");
    withQ("");
    render(
      <BrowserRouter basename="/admin">
        <SearchPage />
      </BrowserRouter>,
    );
    expect(screen.getByText("输入 2–50 字开始搜索")).toBeInTheDocument();
    expect(spy).not.toHaveBeenCalled();
  });
});
