import * as React from "react";
import { Link, useSearchParams } from "react-router";

import { globalSearch, type SearchResponse } from "@/api/search";
import { Badge } from "@/components/ui/badge";

const COUNT_CAP = 1001;
const capLabel = (n: number) => (n >= COUNT_CAP ? "1000+" : String(n));

function GroupHead({ title, count, to, q }: {
  title: string; count: number; to: string; q: string;
}) {
  return (
    <div className="flex items-center gap-2">
      <h3 className="font-mono text-sm text-ink-2">{title}</h3>
      <Badge variant="outline" className="border-line px-1.5 font-mono text-ink-2">
        {capLabel(count)}
      </Badge>
      <Link to={`${to}?q=${encodeURIComponent(q)}`}
        className="ml-auto text-sm font-semibold text-brand hover:text-brand-hover">
        查看全部 →
      </Link>
    </div>
  );
}

export function SearchPage() {
  const [params] = useSearchParams();
  const q = (params.get("q") ?? "").trim();
  const [data, setData] = React.useState<SearchResponse | null>(null);
  const [state, setState] = React.useState<"loading" | "error" | "ready">("loading");

  React.useEffect(() => {
    if (!q) return;
    let alive = true;
    setState("loading");
    globalSearch(q)
      .then((r) => alive && (setData(r), setState("ready")))
      .catch(() => alive && setState("error"));
    return () => { alive = false; };
  }, [q]);

  if (!q) {
    return (
      <section className="space-y-4">
        <h2 className="font-mono text-lg text-ink">全局搜索</h2>
        <p className="text-sm text-ink-3">输入 2–50 字开始搜索</p>
      </section>
    );
  }

  return (
    <section className="space-y-4">
      <h2 className="font-mono text-lg text-ink">全局搜索：{q}</h2>
      {state === "loading" && <p role="status" className="text-sm text-ink-3">加载中…</p>}
      {state === "error" && <p role="alert" className="text-sm text-danger">搜索失败</p>}
      {state === "ready" && data && (
        <>
          <section className="space-y-2">
            <GroupHead title="用户" count={data.users.count} to="/users" q={q} />
            <div className="rounded-lg border border-line bg-surface">
              {data.users.items.map((u) => (
                <div key={u.id} className="border-b border-line px-4 py-2 text-sm last:border-b-0">
                  <Link to={`/users/show/${u.id}`} className="font-mono text-ink">{u.login}</Link>
                  <span className="ml-2 text-xs text-ink-3">{u.bio || "—"}</span>
                </div>
              ))}
              {data.users.items.length === 0 && (
                <p className="px-4 py-3 text-sm text-ink-3">无命中</p>
              )}
            </div>
          </section>
          <section className="space-y-2">
            <GroupHead title="仓库" count={data.repos.count} to="/repos" q={q} />
            <div className="rounded-lg border border-line bg-surface">
              {data.repos.items.map((r) => (
                <div key={r.id} className="border-b border-line px-4 py-2 text-sm last:border-b-0">
                  <Link to={`/repos?q=${encodeURIComponent(r.name)}`}
                    className="font-mono text-ink">{r.name}</Link>
                  <span className="ml-2 text-xs text-ink-3">{r.title || "—"}</span>
                </div>
              ))}
              {data.repos.items.length === 0 && (
                <p className="px-4 py-3 text-sm text-ink-3">无命中</p>
              )}
            </div>
          </section>
          <section className="space-y-2">
            <GroupHead title="评论" count={data.comments.count} to="/comments" q={q} />
            <div className="rounded-lg border border-line bg-surface">
              {data.comments.items.map((c) => (
                <div key={c.id} className="border-b border-line px-4 py-2 text-sm last:border-b-0">
                  {c.hidden && (
                    <Badge variant="outline"
                      className="mr-2 border-line font-mono text-ink-3">已隐藏</Badge>
                  )}
                  <span className="font-mono text-xs text-ink-3">@{c.author_login}</span>
                  <p className="mt-1 text-ink-2">{c.body}</p>
                </div>
              ))}
              {data.comments.items.length === 0 && (
                <p className="px-4 py-3 text-sm text-ink-3">无命中</p>
              )}
            </div>
          </section>
        </>
      )}
    </section>
  );
}

export default SearchPage;
