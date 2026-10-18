import * as React from "react";
import { Bar, CartesianGrid, ComposedChart, Line, Tooltip, XAxis, YAxis } from "recharts";

import { getLlmStats, type LlmStats } from "@/api/llmUsage";
import { Button } from "@/components/ui/button";
import {
  Table, TableBody, TableCell, TableHead, TableHeader, TableRow,
} from "@/components/ui/table";

const EMPTY = "—";

type Range = { key: string; label: string; days: number };
type LoadResult =
  | { rangeKey: string; status: "ready"; data: LlmStats }
  | { rangeKey: string; status: "error"; message: string };

const RANGES: Range[] = [
  { key: "7d", label: "近 7 日", days: 7 },
  { key: "30d", label: "近 30 日", days: 30 },
  { key: "90d", label: "近 90 日", days: 90 },
];

const utcDay = (offsetDays: number): string =>
  new Date(Date.now() - offsetDays * 86_400_000).toISOString().slice(0, 10);

export function LlmUsagePage() {
  const [range, setRange] = React.useState<Range>(RANGES[0]);
  const [result, setResult] = React.useState<LoadResult | null>(null);
  const current = result?.rangeKey === range.key ? result : null;
  const data = current?.status === "ready" ? current.data : null;
  const error = current?.status === "error" ? current.message : null;
  const loading = current === null;

  React.useEffect(() => {
    let alive = true;
    setResult(null);
    void getLlmStats(utcDay(range.days - 1), utcDay(0))
      .then((resp) => {
        if (alive) setResult({ rangeKey: range.key, status: "ready", data: resp });
      })
      .catch((e: Error) => {
        if (alive) setResult({ rangeKey: range.key, status: "error", message: e.message || "加载失败" });
      });
    return () => {
      alive = false;
    };
  }, [range]);

  const daily = data?.daily ?? [];
  const calls = daily.reduce((n, d) => n + d.calls, 0);
  const tokens = daily.reduce((n, d) => n + d.prompt_tokens + d.completion_tokens, 0);
  const errors = daily.reduce((n, d) => n + d.errors, 0);
  const latency =
    calls > 0 ? Math.round(daily.reduce((n, d) => n + d.avg_latency_ms * d.calls, 0) / calls) : null;

  const chartData = daily.map((d) => ({
    label: d.date.slice(5),
    calls: d.calls,
    tokens: d.prompt_tokens + d.completion_tokens,
  }));

  return (
    <section className="space-y-4">
      <header className="flex items-center gap-2">
        <h2 className="font-mono text-lg text-ink">LLM 用量</h2>
        <div className="ml-auto flex items-center gap-2">
          {RANGES.map((r) => (
            <Button key={r.key} type="button" size="sm"
              variant={range.key === r.key ? "default" : "outline"}
              className={range.key === r.key ? "" : "border-line text-ink-2"}
              onClick={() => setRange(r)}>
              {r.label}
            </Button>
          ))}
        </div>
      </header>

      {error && <p role="alert" className="text-sm text-danger">{error}</p>}
      {loading && <p role="status" className="font-mono text-sm text-ink-3">加载中…</p>}

      <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
        {([
          { label: "区间调用数", value: data ? String(calls) : EMPTY },
          { label: "tokens 合计", value: data ? String(tokens) : EMPTY },
          { label: "失败率", value: calls > 0 ? `${((errors / calls) * 100).toFixed(1)}%` : EMPTY },
          { label: "平均耗时", value: latency !== null ? `${latency} ms` : EMPTY },
        ]).map(({ label, value }) => (
          <div key={label} className="rounded-lg border border-line bg-surface p-5">
            <div className="text-sm text-ink-2">{label}</div>
            <div className="mt-2 font-mono text-2xl text-ink">{value}</div>
          </div>
        ))}
      </div>

      {chartData.length > 0 && (
        <div className="rounded-lg border border-line bg-surface p-5">
          <ComposedChart width={760} height={280} data={chartData}>
            <CartesianGrid strokeDasharray="3 3" stroke="#E7E3D8" />
            <XAxis dataKey="label" tick={{ fontSize: 12 }} />
            <YAxis yAxisId="left" tick={{ fontSize: 12 }} />
            <YAxis yAxisId="right" orientation="right" tick={{ fontSize: 12 }} />
            <Tooltip />
            <Bar yAxisId="left" dataKey="calls" name="调用数" fill="#AE5139" />
            <Line yAxisId="right" type="monotone" dataKey="tokens" name="tokens" stroke="#313A45" />
          </ComposedChart>
        </div>
      )}

      <div className="rounded-lg border border-line bg-surface">
        <h3 className="px-4 pt-4 font-mono text-sm text-ink-2">模型分布</h3>
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead className="text-ink-3">模型</TableHead>
              <TableHead className="text-ink-3">调用数</TableHead>
              <TableHead className="text-ink-3">tokens</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {(loading || error || data?.models.length === 0) && (
              <TableRow>
                <TableCell colSpan={3} className={`py-8 text-center ${error ? "text-danger" : "text-ink-3"}`}>
                  {loading ? "加载中…" : error ? "加载失败，请切换区间重试。" : "暂无模型调用。"}
                </TableCell>
              </TableRow>
            )}
            {(data?.models ?? []).map((m) => (
              <TableRow key={m.model}>
                <TableCell className="font-mono text-ink">{m.model || EMPTY}</TableCell>
                <TableCell className="font-mono text-ink-2">{m.calls}</TableCell>
                <TableCell className="font-mono text-ink-2">{m.tokens}</TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </div>

      <div className="rounded-lg border border-line bg-surface">
        <h3 className="px-4 pt-4 font-mono text-sm text-ink-2">仓库 Top 10</h3>
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead className="text-ink-3">仓库</TableHead>
              <TableHead className="text-ink-3">调用数</TableHead>
              <TableHead className="text-ink-3">tokens</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {(loading || error || data?.repos_top.length === 0) && (
              <TableRow>
                <TableCell colSpan={3} className={`py-8 text-center ${error ? "text-danger" : "text-ink-3"}`}>
                  {loading ? "加载中…" : error ? "加载失败，请切换区间重试。" : "暂无仓库消耗。"}
                </TableCell>
              </TableRow>
            )}
            {(data?.repos_top ?? []).map((r) => (
              <TableRow key={r.repo_id}>
                <TableCell className="font-mono text-ink">{r.name}</TableCell>
                <TableCell className="font-mono text-ink-2">{r.calls}</TableCell>
                <TableCell className="font-mono text-ink-2">{r.tokens}</TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </div>
    </section>
  );
}

export default LlmUsagePage;
