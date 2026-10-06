import { describe, expect, it, vi } from "vitest";
import { authProvider } from "./authProvider";

describe("authProvider.check", () => {
  it("401 → OAuth", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(new Response("", { status: 401 }));
    await expect(authProvider.check!()).resolves.toMatchObject({
      authenticated: false, redirectTo: "/api/auth/github?redirect=/admin/",
    });
  });
  it("403 报无权限", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(new Response("", { status: 403 }));
    await expect(authProvider.check!()).rejects.toThrow();
  });
});

describe("authProvider.check · 200", () => {
  it("已认证", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(new Response("", { status: 200 }));
    await expect(authProvider.check!()).resolves.toEqual({ authenticated: true });
  });
});

describe("authProvider.check · 403 错误形状", () => {
  it("Forbidden 无管理权限", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(new Response("", { status: 403 }));
    const error = await authProvider.check!().catch((e: unknown) => e);
    expect(error).toBeInstanceOf(Error);
    expect((error as Error).name).toBe("Forbidden");
    expect((error as Error).message).toBe("无管理权限");
  });
});

describe("authProvider.getIdentity", () => {
  it("返回 /me 主体", async () => {
    const me = { login: "boss", avatar_url: "https://avatars.githubusercontent.com/u/1", is_admin: true };
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(JSON.stringify(me), { status: 200 }),
    );
    await expect(authProvider.getIdentity!()).resolves.toEqual(me);
  });
});

describe("authProvider.logout", () => {
  it("POST /api/auth/logout", async () => {
    const fetchSpy = vi
      .spyOn(globalThis, "fetch")
      .mockResolvedValue(new Response("", { status: 200 }));
    await authProvider.logout!({});
    expect(fetchSpy).toHaveBeenCalledWith(
      "/api/auth/logout",
      expect.objectContaining({ method: "POST", credentials: "include" }),
    );
  });
});
