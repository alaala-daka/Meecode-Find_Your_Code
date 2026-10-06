import * as React from "react";
import { useList, type CrudFilter } from "@refinedev/core";

import {
  bulkHideComments,
  deleteComment,
  getCommentsStats,
  hideComment,
  restoreComment,
  type BulkHideResult,
  type CommentRow,
  type CommentStats,
} from "@/api/comments";
import { ConfirmDialog } from "@/components/ConfirmDialog";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { formatTime } from "@/pages/users/UserList";

const PAGE_SIZE = 10;

type CommentRowAction = "hide" | "restore" | "delete";

const ACTION_LABEL: Record<CommentRowAction, string> = {
  hide: "隐藏",
  restore: "恢复",
  delete: "删除",
};

const STATS_BADGES: Array<{ key: keyof CommentStats; label: string; color: string }> = [
  { key: "pending", label: "待审", color: "text-warn" },
  { key: "visible", label: "可见", color: "text-ok" },
  { key: "hidden", label: "隐藏", color: "text-ink-2" },
  { key: "deleted", label: "已删除", color: "text-ink-3" },
];

const bulkSummary = (r: BulkHideResult): string =>
  `批量隐藏完成：已隐藏 ${r.affected} 条 · 未找到 ${r.not_found.length} 条${
    r.not_found.length ? `（id ${r.not_found.join("、")}）` : ""
  } · 跳过 ${r.skipped.length} 条${r.skipped.length ? `（id ${r.skipped.join("、")}）` : ""}`;

export function CommentStatusBadge({ status }: { status: string }) {
  const color =
    status === "visible"
      ? "text-ok"
      : status === "pending"
        ? "text-warn"
        : status === "deleted"
          ? "text-ink-3"
          : "text-ink-2";
  return (
    <Badge variant="outline" className={`border-line font-mono ${color}`}>
      {status}
    </Badge>
  );
}

export function CommentList() {
  const [status, setStatus] = React.useState("all");
  const [repoSearch, setRepoSearch] = React.useState("");
  const [repoId, setRepoId] = React.useState("");
  const [page, setPage] = React.useState(1);
  const [selected, setSelected] = React.useState<Set<number>>(new Set());
  const [pending, setPending] = React.useState<{ row: CommentRow; action: CommentRowAction } | null>(
    null,
  );
  const [bulkOpen, setBulkOpen] = React.useState(false);
  const [actionError, setActionError] = React.useState<string | null>(null);
  const [bulkResult, setBulkResult] = React.useState<BulkHideResult | null>(null);
  const [stats, setStats] = React.useState<CommentStats | null>(null);

  const filters: CrudFilter[] = React.useMemo(() => {
    const list: CrudFilter[] = [];
    if (status !== "all") list.push({ field: "status", operator: "eq", value: status });
    if (repoId) list.push({ field: "repo_id", operator: "eq", value: repoId });
    return list;
  }, [status, repoId]);

  const { result, query } = useList<CommentRow>({
    resource: "comments",
    pagination: { currentPage: page, pageSize: PAGE_SIZE },
    filters,
  });

  const loadStats = React.useCallback(async () => {
    try {
      setStats(await getCommentsStats());
    } catch {
      /* stats 失败不阻塞列表 */
    }
  }, []);

  React.useEffect(() => {
    void loadStats();
  }, [loadStats, page, status, repoId]);

  const rows = result.data;
  const total = result.total ?? 0;
  const totalPages = Math.max(1, Math.ceil(total / PAGE_SIZE));

  const selectableIds = rows
    .filter((r) => r.status === "visible" || r.status === "pending")
    .map((r) => r.id);
  const allSelected = selectableIds.length > 0 && selectableIds.every((id) => selected.has(id));

  const toggleSelect = (id: number) => {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  const toggleSelectAll = () => {
    setSelected((prev) => {
      const next = new Set(prev);
      if (selectableIds.every((id) => next.has(id))) {
        for (const id of selectableIds) next.delete(id);
      } else {
        for (const id of selectableIds) next.add(id);
      }
      return next;
    });
  };

  const refreshAll = async () => {
    await query.refetch().catch(() => undefined);
    await loadStats();
  };

  const askAction = (row: CommentRow, action: CommentRowAction) => {
    setActionError(null);
    setPending({ row, action });
  };

  const handleAction = async () => {
    if (!pending) return;
    const { row, action } = pending;
    try {
      if (action === "hide") await hideComment(row.id);
      else if (action === "restore") await restoreComment(row.id);
      else await deleteComment(row.id);
    } catch (e) {
      setActionError(`${ACTION_LABEL[action]}失败：${(e as Error).message}`);
      throw e;
    }
    setActionError(null);
    await refreshAll();
  };

  const askBulk = () => {
    setActionError(null);
    setBulkOpen(true);
  };

  const handleBulk = async () => {
    const ids = Array.from(selected).sort((a, b) => a - b);
    try {
      const resultBody = await bulkHideComments(ids);
      setBulkResult(resultBody);
    } catch (e) {
      setActionError(`批量隐藏失败：${(e as Error).message}`);
      throw e;
    }
    setActionError(null);
    setSelected(new Set());
    await refreshAll();
  };

  return (
    <section className="space-y-4">
      <h2 className="font-mono text-lg text-ink">评论管理</h2>

      <div className="flex flex-wrap items-center gap-2">
        {STATS_BADGES.map(({ key, label, color }) => (
          <Badge key={key} variant="outline" className={`border-line font-mono ${color}`}>
            {stats ? `${label} ${stats[key]}` : `${label} —`}
          </Badge>
        ))}
      </div>

      {actionError && !pending && !bulkOpen && <p className="text-sm text-danger">{actionError}</p>}

      {bulkResult && (
        <p role="status" className="text-sm text-ink-2">
          {bulkSummary(bulkResult)}
        </p>
      )}

      <form
        className="flex flex-wrap items-center gap-2"
        onSubmit={(e) => {
          e.preventDefault();
          setPage(1);
          setRepoId(repoSearch.trim());
        }}
      >
        <Input
          type="number"
          value={repoSearch}
          onChange={(e) => setRepoSearch(e.target.value)}
          placeholder="仓库 ID"
          aria-label="仓库 ID"
          className="w-28 border-line"
        />
        <Button type="submit" variant="outline" className="border-line text-ink-2">
          筛选
        </Button>
        <Select
          value={status}
          onValueChange={(v) => {
            setStatus(v);
            setPage(1);
          }}
        >
          <SelectTrigger className="w-32 border-line" aria-label="状态筛选">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="all">全部状态</SelectItem>
            <SelectItem value="pending">pending</SelectItem>
            <SelectItem value="visible">visible</SelectItem>
            <SelectItem value="hidden">hidden</SelectItem>
            <SelectItem value="deleted">deleted</SelectItem>
          </SelectContent>
        </Select>
        <Button
          type="button"
          variant="outline"
          className="border-line text-ink-2"
          disabled={selected.size === 0}
          onClick={askBulk}
        >
          批量隐藏
        </Button>
        <span className="text-sm text-ink-3">已选 {selected.size} 条</span>
      </form>

      <div className="rounded-lg border border-line bg-surface">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>
                <input
                  type="checkbox"
                  aria-label="全选本页"
                  checked={allSelected}
                  onChange={toggleSelectAll}
                />
              </TableHead>
              <TableHead className="text-ink-3">ID</TableHead>
              <TableHead className="text-ink-3">内容</TableHead>
              <TableHead className="text-ink-3">仓库</TableHead>
              <TableHead className="text-ink-3">用户</TableHead>
              <TableHead className="text-ink-3">状态</TableHead>
              <TableHead className="text-ink-3">审核原因</TableHead>
              <TableHead className="text-ink-3">时间</TableHead>
              <TableHead className="text-ink-3">操作</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {query.isPending && (
              <TableRow>
                <TableCell colSpan={9} className="py-8 text-center text-ink-3">
                  加载中…
                </TableCell>
              </TableRow>
            )}
            {query.isError && (
              <TableRow>
                <TableCell colSpan={9} className="py-8 text-center text-danger">
                  加载失败，请稍后重试。
                </TableCell>
              </TableRow>
            )}
            {!query.isPending && !query.isError && rows.length === 0 && (
              <TableRow>
                <TableCell colSpan={9} className="py-8 text-center text-ink-3">
                  暂无评论。
                </TableCell>
              </TableRow>
            )}
            {rows.map((row) => {
              const selectable = row.status === "visible" || row.status === "pending";
              return (
                <TableRow key={row.id}>
                  <TableCell>
                    {selectable && (
                      <input
                        type="checkbox"
                        aria-label={`选择评论 ${row.id}`}
                        checked={selected.has(row.id)}
                        onChange={() => toggleSelect(row.id)}
                      />
                    )}
                  </TableCell>
                  <TableCell className="font-mono text-ink-2">{row.id}</TableCell>
                  <TableCell className="max-w-64 truncate text-ink-2">{row.content}</TableCell>
                  <TableCell className="font-mono text-ink">{row.repo_full_name}</TableCell>
                  <TableCell className="font-mono text-ink-2">{row.user_login}</TableCell>
                  <TableCell>
                    <CommentStatusBadge status={row.status} />
                  </TableCell>
                  <TableCell>
                    {row.moderation_reason ? (
                      <Badge variant="outline" className="border-line font-mono text-warn">
                        {row.moderation_reason}
                      </Badge>
                    ) : (
                      <span className="text-ink-4">—</span>
                    )}
                  </TableCell>
                  <TableCell className="font-mono text-xs text-ink-2">
                    {formatTime(row.created_at)}
                  </TableCell>
                  <TableCell>
                    <div className="flex flex-wrap items-center gap-1">
                      {selectable && (
                        <Button type="button" size="sm" onClick={() => askAction(row, "hide")}>
                          隐藏
                        </Button>
                      )}
                      {row.status === "hidden" && (
                        <Button
                          type="button"
                          size="sm"
                          variant="outline"
                          className="border-line text-ink-2"
                          onClick={() => askAction(row, "restore")}
                        >
                          恢复
                        </Button>
                      )}
                      {row.status !== "deleted" && (
                        <Button
                          type="button"
                          size="sm"
                          variant="destructive"
                          onClick={() => askAction(row, "delete")}
                        >
                          删除
                        </Button>
                      )}
                    </div>
                  </TableCell>
                </TableRow>
              );
            })}
          </TableBody>
        </Table>
      </div>

      <div className="flex items-center justify-between">
        <span className="text-sm text-ink-3">共 {total} 条评论</span>
        <div className="flex items-center gap-2">
          <Button
            type="button"
            variant="outline"
            size="sm"
            className="border-line text-ink-2"
            disabled={page <= 1 || query.isPending}
            onClick={() => setPage((p) => Math.max(1, p - 1))}
          >
            上一页
          </Button>
          <span className="font-mono text-sm text-ink-2">
            {page} / {totalPages}
          </span>
          <Button
            type="button"
            variant="outline"
            size="sm"
            className="border-line text-ink-2"
            disabled={page >= totalPages || query.isPending}
            onClick={() => setPage((p) => p + 1)}
          >
            下一页
          </Button>
        </div>
      </div>

      {pending && (
        <ConfirmDialog
          open
          onOpenChange={(open) => {
            if (!open) setPending(null);
          }}
          title={`确认${ACTION_LABEL[pending.action]}`}
          description={
            pending.action === "hide"
              ? `将评论 #${pending.row.id}（${pending.row.repo_full_name}）隐藏，隐藏后前台不可见。`
              : pending.action === "restore"
                ? `将评论 #${pending.row.id}（${pending.row.repo_full_name}）恢复为可见。`
                : `删除评论 #${pending.row.id}（${pending.row.repo_full_name}）。删除为终态，不可恢复。`
          }
          danger={pending.action === "delete"}
          error={actionError}
          onConfirm={handleAction}
        />
      )}

      {bulkOpen && (
        <ConfirmDialog
          open
          onOpenChange={(open) => {
            if (!open) setBulkOpen(false);
          }}
          title="确认批量隐藏"
          description={`将选中的 ${selected.size} 条评论批量隐藏（visible|pending → hidden）。`}
          error={actionError}
          onConfirm={handleBulk}
        />
      )}
    </section>
  );
}

export default CommentList;
