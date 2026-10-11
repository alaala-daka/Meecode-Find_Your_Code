import { fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter, Route, Routes, useLocation } from "react-router";
import { afterEach, describe, expect, it, vi } from "vitest";

vi.mock("@refinedev/core", () => ({
  useGetIdentity: () => ({ data: { login: "boss", avatar_url: "" } }),
  useLogout: () => ({ mutate: () => {} }),
}));

import { AppLayout } from "./AppLayout";

afterEach(() => vi.restoreAllMocks());

function SearchProbe() {
  const location = useLocation();
  return <div>{`${location.pathname}${location.search}`}</div>;
}

describe("AppLayout · 菜单", () => {
  it("二期四项可导航，登录日志转正", () => {
    render(
      <MemoryRouter>
        <AppLayout />
      </MemoryRouter>,
    );
    for (const label of ["站点流量", "API 管控", "系统配置", "审计日志"]) {
      expect(screen.getByRole("link", { name: label })).toHaveAttribute("href");
    }
    expect(screen.getByRole("link", { name: /登录日志/ })).toHaveAttribute(
      "href",
      "/login-events",
    );
    expect(screen.queryByText("三期")).toBeNull();
    expect(screen.queryByText("二期")).toBeNull();
  });

  it("登录日志菜单转正且失败徽章>0 红标", async () => {
    vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
      const url = String(input);
      if (url.includes("/login-events")) {
        return new Response(JSON.stringify({ data: [], total: 3 }), { status: 200 });
      }
      return new Response(JSON.stringify({}), { status: 200 });
    });
    render(
      <MemoryRouter>
        <AppLayout />
      </MemoryRouter>,
    );
    const link = await screen.findByRole("link", { name: /登录日志/ });
    expect(link).toHaveAttribute("href", "/login-events");
    expect(await screen.findByText("3")).toBeInTheDocument();
  });

  it("搜索框 Enter 跳转 /search?q=", async () => {
    render(
      <MemoryRouter initialEntries={["/"]}>
        <Routes>
          <Route element={<AppLayout />}>
            <Route path="/" element={<div>首页</div>} />
            <Route path="/search" element={<SearchProbe />} />
          </Route>
        </Routes>
      </MemoryRouter>,
    );
    const input = screen.getByRole("textbox", { name: "全局搜索" });
    fireEvent.change(input, { target: { value: "meecode" } });
    fireEvent.submit(input.closest("form") as HTMLFormElement);
    expect(await screen.findByText("/search?q=meecode")).toBeInTheDocument();
  });
});
