import * as React from "react";
import { Refine, useIsAuthenticated } from "@refinedev/core";
import routerProvider from "@refinedev/react-router";
import { BrowserRouter, Route, Routes } from "react-router";

import { AppLayout } from "@/components/AppLayout";
import { Button } from "@/components/ui/button";
import { CommentList } from "@/pages/comments/CommentList";
import { DashboardPage } from "@/pages/DashboardPage";
import { LoginDeniedPage } from "@/pages/LoginDeniedPage";
import { RepoList } from "@/pages/repos/RepoList";
import { UserList } from "@/pages/users/UserList";
import { UserShow } from "@/pages/users/UserShow";
import { authProvider, OAUTH_ENTRY } from "@/providers/authProvider";
import { dataProvider } from "@/providers/dataProvider";

const resources = [
  { name: "dashboard", list: "/", meta: { label: "仪表盘" } },
  { name: "users", list: "/users", show: "/users/show/:id", meta: { label: "用户管理" } },
  { name: "repos", list: "/repos", meta: { label: "仓库管理" } },
  { name: "comments", list: "/comments", meta: { label: "评论管理" } },
];

function AuthGate({ children }: { children: React.ReactNode }) {
  const { data, error, isFetching, isError, refetch } = useIsAuthenticated();

  React.useEffect(() => {
    if (data && !data.authenticated) {
      window.location.assign(data.redirectTo ?? OAUTH_ENTRY);
    }
  }, [data]);

  if (isError) {
    if ((error as Error | undefined)?.name === "Forbidden") {
      return <LoginDeniedPage />;
    }
    return (
      <main className="flex min-h-screen items-center justify-center bg-paper">
        <section className="rounded-lg border border-line bg-surface p-6 text-center">
          <p className="text-sm text-ink-2">身份校验失败，请稍后重试。</p>
          <Button
            type="button"
            variant="outline"
            className="mt-4 border-line text-ink-2"
            onClick={() => refetch()}
          >
            重试
          </Button>
        </section>
      </main>
    );
  }

  if (isFetching || !data?.authenticated) {
    return (
      <main className="flex min-h-screen items-center justify-center bg-paper">
        <span className="font-mono text-sm text-ink-3">正在验证管理员身份…</span>
      </main>
    );
  }

  return <>{children}</>;
}

function PendingPage({ title }: { title: string }) {
  return (
    <section className="rounded-lg border border-line bg-surface p-6">
      <h2 className="font-mono text-lg text-ink">{title}</h2>
      <p className="mt-2 text-sm text-ink-3">建设中（后续任务交付）。</p>
    </section>
  );
}

export default function App() {
  return (
    <BrowserRouter basename="/admin">
      <Refine
        routerProvider={routerProvider}
        dataProvider={dataProvider}
        authProvider={authProvider}
        resources={resources}
        options={{ disableTelemetry: true, disableRouteChangeHandler: true }}
      >
        <AuthGate>
          <Routes>
            <Route element={<AppLayout />}>
              <Route index element={<DashboardPage />} />
              <Route path="/users" element={<UserList />} />
              <Route path="/users/show/:id" element={<UserShow />} />
              <Route path="/repos" element={<RepoList />} />
              <Route path="/comments" element={<CommentList />} />
              <Route path="*" element={<PendingPage title="页面不存在" />} />
            </Route>
          </Routes>
        </AuthGate>
      </Refine>
    </BrowserRouter>
  );
}
