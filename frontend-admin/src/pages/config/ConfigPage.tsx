import * as React from "react";

import { getConfig, updateConfig, type ConfigRow } from "@/api/config";
import { ConfirmDialog } from "@/components/ConfirmDialog";
import { Button } from "@/components/ui/button";

type Pending = { row: ConfigRow; value: string } | null;

const fmt = (ts: number): string => (ts ? new Date(ts * 1000).toLocaleString() : "—");

export function ConfigPage() {
  const [rows, setRows] = React.useState<ConfigRow[]>([]);
  const [draft, setDraft] = React.useState<Record<string, string>>({});
  const [pending, setPending] = React.useState<Pending>(null);
  const [dialogError, setDialogError] = React.useState<string | null>(null);
  const [error, setError] = React.useState<string | null>(null);

  const load = React.useCallback(async () => {
    try {
      const resp = await getConfig();
      setRows(resp.data);
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
      await updateConfig({
        key: pending.row.key,
        value: pending.value,
        version: pending.row.version,
      });
      setDialogError(null);
      await load();
    } catch (e) {
      setDialogError((e as Error).message);
      throw e; // ConfirmDialog 保留弹窗，错误展示在弹窗内
    }
  };

  return (
    <section className="space-y-4">
      <h2 className="font-mono text-lg text-ink">系统配置</h2>
      {error && <p role="alert" className="text-sm text-danger">{error}</p>}
      <table className="w-full rounded-lg border border-line bg-surface text-sm">
        <thead>
          <tr className="border-b border-line text-left text-ink-3">
            <th className="px-4 py-3 font-normal">键</th>
            <th className="px-4 py-3 font-normal">值</th>
            <th className="px-4 py-3 font-normal">版本</th>
            <th className="px-4 py-3 font-normal">更新时间</th>
            <th className="px-4 py-3 font-normal">更新人</th>
            <th className="px-4 py-3 font-normal">操作</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => {
            const secret = row.value === "***";
            return (
              <tr key={row.key} className="border-b border-line last:border-0">
                <td className="px-4 py-3 font-mono text-ink">{row.key}</td>
                <td className="px-4 py-3">
                  {secret ? (
                    <>
                      <span className="font-mono text-ink-2">***</span>
                      <span className="ml-2 text-xs text-ink-3">密钥字段不可经界面修改</span>
                    </>
                  ) : (
                    <input
                      aria-label={`${row.key} 值`}
                      className="w-40 rounded-sm border border-line bg-paper px-2 py-1 font-mono text-ink"
                      value={draft[row.key] ?? row.value}
                      onChange={(e) =>
                        setDraft((d) => ({ ...d, [row.key]: e.target.value }))
                      }
                    />
                  )}
                </td>
                <td className="px-4 py-3 font-mono text-ink-2">{row.version}</td>
                <td className="px-4 py-3 font-mono text-ink-2">{fmt(row.updated_at)}</td>
                <td className="px-4 py-3 text-ink-2">{row.updated_by || "—"}</td>
                <td className="px-4 py-3">
                  {!secret && (
                    <Button
                      type="button"
                      size="sm"
                      variant="outline"
                      className="border-line text-ink-2"
                      aria-label={`${row.key} 保存`}
                      onClick={() =>
                        setPending({ row, value: draft[row.key] ?? row.value })
                      }
                    >
                      保存
                    </Button>
                  )}
                </td>
              </tr>
            );
          })}
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
        title="确认修改"
        description={
          pending ? `确定将 ${pending.row.key} 更新为「${pending.value}」？` : ""
        }
        confirmText="确认"
        error={dialogError}
        onConfirm={confirm}
      />
    </section>
  );
}

export default ConfigPage;
