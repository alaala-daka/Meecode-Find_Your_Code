import type { AuthProvider } from "@refinedev/core";

export const OAUTH_ENTRY = "/api/auth/github?redirect=/admin/";

const ME_URL = "/api/admin/me";
const LOGOUT_URL = "/api/auth/logout";

export interface AdminIdentity {
  login: string;
  avatar_url: string;
  is_admin: boolean;
}

export class ForbiddenError extends Error {
  constructor(message = "无管理权限") {
    super(message);
    this.name = "Forbidden";
  }
}

const getStatus = (error: unknown): number | undefined => {
  if (typeof error !== "object" || error === null) return undefined;
  const e = error as { status?: unknown; statusCode?: unknown; response?: { status?: unknown } };
  const raw = e.response?.status ?? e.status ?? e.statusCode;
  return typeof raw === "number" ? raw : undefined;
};

export const authProvider: AuthProvider = {
  login: async () => {
    if (typeof window !== "undefined") {
      window.location.assign(OAUTH_ENTRY);
    }
    return { success: true };
  },

  logout: async (params?: { redirectPath?: string }) => {
    await fetch(LOGOUT_URL, { method: "POST", credentials: "include" });
    const to = params?.redirectPath ?? "/";
    if (typeof window !== "undefined") {
      window.location.assign(to);
    }
    return { success: true };
  },

  check: async () => {
    const res = await fetch(ME_URL, { credentials: "include" });
    if (res.status === 401) {
      return { authenticated: false, redirectTo: OAUTH_ENTRY };
    }
    if (res.status === 403) {
      throw new ForbiddenError();
    }
    if (!res.ok) {
      throw new Error(`身份校验失败（HTTP ${res.status}）`);
    }
    return { authenticated: true };
  },

  getIdentity: async () => {
    const res = await fetch(ME_URL, { credentials: "include" });
    if (!res.ok) {
      throw new Error(`获取管理员信息失败（HTTP ${res.status}）`);
    }
    const identity: AdminIdentity = await res.json();
    return identity;
  },

  onError: async (error) => {
    if (getStatus(error) === 401) {
      if (typeof window !== "undefined") {
        window.location.assign(OAUTH_ENTRY);
      }
      return { error };
    }
    return { error };
  },
};
