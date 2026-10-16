import * as React from "react";

import { useGetIdentity, useLogout } from "@refinedev/core";
import { NavLink, Outlet, useLocation, useNavigate } from "react-router";

import { getFeedback } from "@/api/feedback";
import { getLoginEvents } from "@/api/loginEvents";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import type { AdminIdentity } from "@/providers/authProvider";

type MenuItem = { label: string; to: string; badge?: "loginFails" | "feedbackPending" };

const MENU: MenuItem[] = [
  { label: "仪表盘", to: "/" },
  { label: "站点流量", to: "/traffic" },
  { label: "LLM 用量", to: "/llm-usage" },
  { label: "用户管理", to: "/users" },
  { label: "仓库管理", to: "/repos" },
  { label: "评论管理", to: "/comments" },
  { label: "反馈收件箱", to: "/feedback", badge: "feedbackPending" },
  { label: "API 管控", to: "/api-policies" },
  { label: "系统配置", to: "/config" },
  { label: "审计日志", to: "/audit-logs" },
  { label: "登录日志", to: "/login-events", badge: "loginFails" },
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
  const location = useLocation();
  const [fails, setFails] = React.useState(0);
  const [pendingFb, setPendingFb] = React.useState(0);
  const [term, setTerm] = React.useState("");
  const navigate = useNavigate();

  React.useEffect(() => {
    let alive = true;
    const from = new Date().toISOString().slice(0, 10);
    getLoginEvents({ ok: "0", from, page: 1, page_size: 1 })
      .then((b) => alive && setFails(b.total ?? 0))
      .catch(() => alive && setFails(0));
    getFeedback({ status: "pending", page: 1, page_size: 1 })
      .then((b) => alive && setPendingFb(b.total ?? 0))
      .catch(() => alive && setPendingFb(0));
    return () => {
      alive = false;
    };
  }, [location.pathname]);

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
          {MENU.map((item) => (
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
              <span className="flex items-center justify-between">
                <span>{item.label}</span>
                {(() => {
                  const n = item.badge === "loginFails" ? fails
                    : item.badge === "feedbackPending" ? pendingFb : 0;
                  return n > 0 ? (
                    <Badge variant="outline"
                      className="border-line px-1.5 font-mono text-danger">{n}</Badge>
                  ) : null;
                })()}
              </span>
            </NavLink>
          ))}
        </nav>
      </aside>
      <div className="flex min-w-0 flex-1 flex-col">
        <header className="flex h-14 shrink-0 items-center justify-end gap-4 border-b border-line bg-surface px-6">
          <form
            className="mr-auto"
            onSubmit={(e) => {
              e.preventDefault();
              const t = term.trim();
              if (t) navigate(`/search?q=${encodeURIComponent(t)}`);
            }}
          >
            <Input
              value={term}
              onChange={(e) => setTerm(e.target.value)}
              placeholder="搜索用户 / 仓库 / 评论"
              className="w-64 border-line"
              aria-label="全局搜索"
            />
          </form>
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
