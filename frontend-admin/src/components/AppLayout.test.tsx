import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router";
import { describe, expect, it, vi } from "vitest";

vi.mock("@refinedev/core", () => ({
  useGetIdentity: () => ({ data: { login: "boss", avatar_url: "" } }),
  useLogout: () => ({ mutate: () => {} }),
}));

import { AppLayout } from "./AppLayout";

describe("AppLayout · 菜单", () => {
  it("二期四项可导航，登录日志徽章为三期", () => {
    render(
      <MemoryRouter>
        <AppLayout />
      </MemoryRouter>,
    );
    for (const label of ["站点流量", "API 管控", "系统配置", "审计日志"]) {
      expect(screen.getByRole("link", { name: label })).toHaveAttribute("href");
    }
    expect(screen.getByText("三期")).toBeInTheDocument();
    expect(screen.queryByText("二期")).toBeNull();
  });
});
