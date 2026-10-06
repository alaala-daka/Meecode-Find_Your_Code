import * as React from "react";

import { getOverview, type Overview } from "@/api/overview";
import { Badge } from "@/components/ui/badge";

const EMPTY = "—";

type LiveCard = { key: keyof Overview; label: string };

const LIVE_CARDS: LiveCard[] = [
  { key: "total_users", label: "注册总数" },
  { key: "new_users_today", label: "今日新增" },
  { key: "total_repos", label: "仓库总数" },
  { key: "published_repos", label: "已上架" },
  { key: "delisted_repos", label: "已下架" },
  { key: "pending_comments", label: "待审评论" },
];

const PHASE2_CARDS = [{ label: "本年累计访问" }, { label: "当前在线" }];

const showValue = (value: number | undefined): string =>
  typeof value === "number" ? String(value) : EMPTY;

export function DashboardPage() {
  const [overview, setOverview] = React.useState<Overview | null>(null);

  React.useEffect(() => {
    let alive = true;
    void getOverview()
      .then((data) => {
        if (alive) setOverview(data);
      })
      .catch(() => {
        /* 拉取失败保持 `—` 占位，不伪造 0 */
      });
    return () => {
      alive = false;
    };
  }, []);

  return (
    <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
      {LIVE_CARDS.map(({ key, label }) => (
        <div key={key} className="rounded-lg border border-line bg-surface p-5">
          <div className="text-sm text-ink-2">{label}</div>
          <div className="mt-2 font-mono text-2xl text-ink">{showValue(overview?.[key])}</div>
        </div>
      ))}
      {PHASE2_CARDS.map(({ label }) => (
        <div key={label} className="rounded-lg border border-line bg-tint p-5">
          <div className="flex items-center justify-between gap-2">
            <div className="text-sm text-ink-3">{label}</div>
            <Badge variant="outline" className="border-line px-1.5 text-ink-4">
              二期
            </Badge>
          </div>
          <div className="mt-2 font-mono text-2xl text-ink-3">{EMPTY}</div>
        </div>
      ))}
    </div>
  );
}

export default DashboardPage;
