import * as React from "react";

import { getApiStats } from "@/api/traffic";
import { getPolicies, updatePolicy, type PolicyRow } from "@/api/policies";
import { ConfirmDialog } from "@/components/ConfirmDialog";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";

const PROTECTED = new Set(["default", "admin"]);

type Pending = {
  row: PolicyRow;
  patch: { enabled?: boolean; limit_per_min?: number };
  title: string;
  description: string;
} | null;

export function ApiPoliciesPage() {
  const [rows, setRows] = React.useState<PolicyRow[]>([]);
  const [stats, setStats] = React.useState<Record<string, { calls: number; error_rate: number }>>({});
  const [draft, setDraft] = React.useState<Record<string, string>>({});
  const [pending, setPending] = React.useState<Pending>(null);
  const [dialogError, setDialogError] = React.useState<string | null>(null);
  const [error, setError] = React.useState<string | null>(null);

  const load = React.useCallback(async () => {
    try {
      const [p, s] = await Promise.all([getPolicies(), getApiStats("7d")]);
      setRows(p.data);
      setStats(Object.fromEntries(s.buckets.map((b) => [b.route_key, b])));
      setError(null);
    } catch (e) {
      setError((e as Error).message);
    }
  }, []);

  React.useEffect(() => {
    void load();
  }, [load]);

  const confirm = async () => {
    if (!pending) return;
    try {
      await updatePolicy(pending.row.route_key, pending.patch);
      setDialogError(null);
      await load();
    } catch (e) {
      setDialogError((e as Error).message);
      throw e; // ConfirmDialog 保留弹窗，错误展示在弹窗内
    }
  };

  return (
    <section className="space-y-4">
      <h2 className="font-mono text-lg text-ink">API 管控</h2>
      {error && <p role="alert" className="text-sm text-danger">{error}</p>}
      <table className="w-full rounded-lg border border-line bg-surface text-sm">
        <thead>
          <tr className="border-b border-line text-left text-ink-3">
            <th className="px-4 py-3 font-normal">桶名</th>
            <th className="px-4 py-3 font-normal">调用量（7d）</th>
            <th className="px-4 py-3 font-normal">错误率（7d）</th>
            <th className="px-4 py-3 font-normal">限额（次/分）</th>
            <th className="px-4 py-3 font-normal">接口开关</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr key={row.route_key} className="border-b border-line last:border-0">
              <td className="px-4 py-3 font-mono text-ink">
                {row.route_key}
                {PROTECTED.has(row.route_key) && (
                  <Badge variant="outline" className="ml-2 border-line px-1.5 text-ink-4">
                    保护
                  </Badge>
                )}
              </td>
              <td className="px-4 py-3 font-mono text-ink-2">{stats[row.route_key]?.calls ?? 0}</td>
              <td className="px-4 py-3 font-mono text-ink-2">
                {((stats[row.route_key]?.error_rate ?? 0) * 100).toFixed(1)}%
              </td>
              <td className="px-4 py-3">
                <input
                  type="number"
                  min={1}
                  aria-label={`${row.route_key} 限额`}
                  className="w-24 rounded-sm border border-line bg-paper px-2 py-1 font-mono text-ink"
                  value={draft[row.route_key] ?? String(row.limit_per_min)}
                  onChange={(e) => setDraft((d) => ({ ...d, [row.route_key]: e.target.value }))}
                />
                <Button type="button" size="sm" variant="outline"
                  className="ml-2 border-line text-ink-2"
                  aria-label={`${row.route_key} 保存`}
                  onClick={() => setPending({
                    row,
                    patch: { limit_per_min: Number(draft[row.route_key] ?? row.limit_per_min) },
                    title: "确认修改",
                    description: `确定调整 ${row.route_key} 桶限额？立即生效。`,
                  })}>
                  保存
                </Button>
              </td>
              <td className="px-4 py-3">
                <Button type="button" size="sm"
                  variant={row.enabled ? "destructive" : "default"}
                  disabled={PROTECTED.has(row.route_key)}
                  title={PROTECTED.has(row.route_key) ? "default/admin 桶不可停用（防自锁）" : undefined}
                  onClick={() => setPending({
                    row,
                    patch: { enabled: !row.enabled },
                    title: "确认修改",
                    description: row.enabled
                      ? `停用 ${row.route_key} 桶后命中请求将返回 403。`
                      : `启用 ${row.route_key} 桶。`,
                  })}>
                  {row.enabled ? "停用" : "启用"}
                </Button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      <ConfirmDialog
        open={pending !== null}
        onOpenChange={(open) => {
          if (!open) {
            setPending(null);
            setDialogError(null);
          }
        }}
        title={pending?.title ?? ""}
        description={pending?.description ?? ""}
        confirmText="确认"
        danger={pending?.patch.enabled === false}
        error={dialogError}
        onConfirm={confirm}
      />
    </section>
  );
}

export default ApiPoliciesPage;
