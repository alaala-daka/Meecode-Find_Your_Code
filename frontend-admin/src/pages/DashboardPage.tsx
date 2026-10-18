import * as React from "react";

import { getOverview, type LlmMonth, type Overview } from "@/api/overview";

const EMPTY = "—";

// llm_month 是对象字段，不进 LIVE_CARDS 数值槽（Plan 期修正 5）
type LiveCard = { key: Exclude<keyof Overview, "llm_month">; label: string };

const LIVE_CARDS: LiveCard[] = [
  { key: "total_users", label: "注册总数" },
  { key: "new_users_today", label: "今日新增" },
  { key: "total_repos", label: "仓库总数" },
  { key: "published_repos", label: "已上架" },
  { key: "delisted_repos", label: "已下架" },
  { key: "pending_comments", label: "待审评论" },
  { key: "year_pv", label: "本年累计访问" },
  { key: "today_pv", label: "今日访问" },
  { key: "online", label: "当前在线" },
];

const showValue = (value: number | undefined): string =>
  typeof value === "number" ? String(value) : EMPTY;

const llmValue = (m: LlmMonth | undefined): string => (m ? String(m.calls) : EMPTY);
const llmTokens = (m: LlmMonth | undefined): string =>
  m ? `tokens 合计 ${m.prompt_tokens + m.completion_tokens}` : EMPTY;

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
      <div className="rounded-lg border border-line bg-surface p-5">
        <div className="text-sm text-ink-2">本月 LLM 调用</div>
        <div className="mt-2 font-mono text-2xl text-ink">{llmValue(overview?.llm_month)}</div>
        <div className="mt-1 font-mono text-xs text-ink-3">{llmTokens(overview?.llm_month)}</div>
      </div>
    </div>
  );
}

export default DashboardPage;
