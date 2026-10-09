import * as React from "react";

import { getAuditLogs, type AuditRow } from "@/api/audit";
import { Button } from "@/components/ui/button";

const PAGE_SIZE = 20;

export function AuditLogPage() {
  const [actionInput, setActionInput] = React.useState("");
  const [adminInput, setAdminInput] = React.useState("");
  const [action, setAction] = React.useState("");
  const [admin, setAdmin] = React.useState("");
  const [page, setPage] = React.useState(1);
  const [rows, setRows] = React.useState<AuditRow[]>([]);
  const [total, setTotal] = React.useState(0);
  const [error, setError] = React.useState<string | null>(null);

  React.useEffect(() => {
    let alive = true;
    void getAuditLogs({ action, admin, page, page_size: PAGE_SIZE })
      .then((resp) => {
        if (alive) {
          setRows(resp.data);
          setTotal(resp.total);
          setError(null);
        }
      })
      .catch((e: Error) => {
        if (alive) setError(e.message);
      });
    return () => {
      alive = false;
    };
  }, [action, admin, page]);

  return (
    <section className="space-y-4">
      <h2 className="font-mono text-lg text-ink">审计日志</h2>
      <div className="flex items-end gap-3">
        <label className="text-sm text-ink-2">
          动作
          <input
            aria-label="动作"
            className="ml-2 rounded-sm border border-line bg-paper px-2 py-1 font-mono text-ink"
            value={actionInput}
            onChange={(e) => setActionInput(e.target.value)}
          />
        </label>
        <label className="text-sm text-ink-2">
          管理员
          <input
            aria-label="管理员"
            className="ml-2 rounded-sm border border-line bg-paper px-2 py-1 font-mono text-ink"
            value={adminInput}
            onChange={(e) => setAdminInput(e.target.value)}
          />
        </label>
        <Button
          type="button"
          size="sm"
          onClick={() => {
            setAction(actionInput);
            setAdmin(adminInput);
            setPage(1);
          }}
        >
          查询
        </Button>
      </div>
      {error && <p role="alert" className="text-sm text-danger">{error}</p>}
      <table className="w-full rounded-lg border border-line bg-surface text-sm">
        <thead>
          <tr className="border-b border-line text-left text-ink-3">
            <th className="px-4 py-3 font-normal">时间</th>
            <th className="px-4 py-3 font-normal">管理员</th>
            <th className="px-4 py-3 font-normal">动作</th>
            <th className="px-4 py-3 font-normal">目标</th>
            <th className="px-4 py-3 font-normal">详情</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr key={row.id} className="border-b border-line last:border-0">
              <td className="px-4 py-3 font-mono text-ink-2">{row.ts}</td>
              <td className="px-4 py-3 font-mono text-ink">{row.admin_login}</td>
              <td className="px-4 py-3 font-mono text-ink">{row.action}</td>
              <td className="px-4 py-3 font-mono text-ink-2">
                {row.target_id ? `${row.target_type}:${row.target_id}` : row.target_type}
              </td>
              <td className="px-4 py-3">
                {row.detail == null ? (
                  "—"
                ) : (
                  <pre className="whitespace-pre-wrap font-mono text-xs text-ink-2">
                    {JSON.stringify(row.detail, null, 2)}
                  </pre>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      <div className="flex items-center gap-3">
        <Button
          type="button"
          size="sm"
          variant="outline"
          className="border-line text-ink-2"
          disabled={page <= 1}
          onClick={() => setPage((p) => p - 1)}
        >
          上一页
        </Button>
        <span className="font-mono text-sm text-ink-2">第 {page} 页</span>
        <Button
          type="button"
          size="sm"
          variant="outline"
          className="border-line text-ink-2"
          disabled={page * PAGE_SIZE >= total}
          onClick={() => setPage((p) => p + 1)}
        >
          下一页
        </Button>
      </div>
    </section>
  );
}

export default AuditLogPage;
