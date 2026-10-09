import { useGetIdentity, useLogout } from "@refinedev/core";
import { NavLink, Outlet } from "react-router";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import type { AdminIdentity } from "@/providers/authProvider";

type MenuItem = { label: string; to: string; phase?: undefined } | { label: string; phase: string; to?: undefined };

const MENU: MenuItem[] = [
  { label: "仪表盘", to: "/" },
  { label: "站点流量", to: "/traffic" },
  { label: "用户管理", to: "/users" },
  { label: "仓库管理", to: "/repos" },
  { label: "评论管理", to: "/comments" },
  { label: "API 管控", to: "/api-policies" },
  { label: "系统配置", phase: "二期" },
  { label: "审计日志", phase: "二期" },
  { label: "登录日志", phase: "二期" },
];

function Identity() {
  const { data: identity } = useGetIdentity<AdminIdentity>();
  if (!identity) return null;
  return (
    <div className="flex items-center gap-2">
      {identity.avatar_url ? (
        <img
          src={identity.avatar_url}
          alt=""
          className="h-8 w-8 rounded-full border border-line"
        />
      ) : (
        <span className="flex h-8 w-8 items-center justify-center rounded-full bg-tint font-mono text-sm text-ink-2">
          {identity.login.slice(0, 1).toUpperCase()}
        </span>
      )}
      <span className="font-mono text-sm text-ink">{identity.login}</span>
    </div>
  );
}

export function AppLayout() {
  const { mutate: logout } = useLogout();

  return (
    <div className="flex min-h-screen bg-paper text-ink">
      <aside className="flex w-60 shrink-0 flex-col border-r border-line bg-paper">
        <div className="px-5 py-5">
          <span className="font-mono text-lg text-ink">
            觅码 <span className="text-ink-3">Meecode</span>
          </span>
          <div className="mt-1 text-xs text-ink-4">管理台</div>
        </div>
        <nav className="flex-1 space-y-1 px-3 pb-6">
          {MENU.map((item) =>
            item.to ? (
              <NavLink
                key={item.label}
                to={item.to}
                end={item.to === "/"}
                className={({ isActive }) =>
                  [
                    "flex items-center justify-between rounded-sm px-3 py-2 text-sm transition-colors duration-[180ms]",
                    isActive
                      ? "bg-tint font-medium text-ink"
                      : "text-ink-2 hover:bg-tint hover:text-ink",
                  ].join(" ")
                }
              >
                {item.label}
              </NavLink>
            ) : (
              <div
                key={item.label}
                aria-disabled="true"
                title={`${item.label}（${item.phase}开放）`}
                className="flex cursor-not-allowed items-center justify-between rounded-sm px-3 py-2 text-sm text-ink-4"
              >
                <span>{item.label}</span>
                <Badge variant="outline" className="border-line px-1.5 text-ink-4">
                  {item.phase}
                </Badge>
              </div>
            ),
          )}
        </nav>
      </aside>
      <div className="flex min-w-0 flex-1 flex-col">
        <header className="flex h-14 shrink-0 items-center justify-end gap-4 border-b border-line bg-surface px-6">
          <Identity />
          <Button
            type="button"
            variant="outline"
            size="sm"
            className="border-line text-ink-2"
            onClick={() => logout()}
          >
            退出登录
          </Button>
        </header>
        <main className="flex-1 p-6">
          <Outlet />
        </main>
      </div>
    </div>
  );
}

export default AppLayout;
