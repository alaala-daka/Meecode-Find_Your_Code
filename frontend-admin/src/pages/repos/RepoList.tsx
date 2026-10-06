import * as React from "react";
import { useList, type CrudFilter } from "@refinedev/core";

import {
  repoStateAction,
  type RepoAction,
  type RepoRow,
} from "@/api/repos";
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
import { RepoEdit } from "./RepoEdit";

const PAGE_SIZE = 10;

const ACTION_LABEL: Record<RepoAction, string> = {
  publish: "上架",
  delist: "下架",
  restore: "恢复",
};

export function RepoStatusBadge({ status }: { status: string }) {
  const color =
    status === "published" ? "text-ok" : status === "delisted" ? "text-danger" : "text-warn";
  return (
    <Badge variant="outline" className={`border-line font-mono ${color}`}>
      {status}
    </Badge>
  );
}

export function RepoList() {
  const [search, setSearch] = React.useState("");
  const [q, setQ] = React.useState("");
  const [status, setStatus] = React.useState("all");
  const [page, setPage] = React.useState(1);
  const [pending, setPending] = React.useState<{ row: RepoRow; action: RepoAction } | null>(null);
  const [editing, setEditing] = React.useState<RepoRow | null>(null);
  const [actionError, setActionError] = React.useState<string | null>(null);

  const filters: CrudFilter[] = React.useMemo(() => {
    const list: CrudFilter[] = [];
    if (q) list.push({ field: "q", operator: "contains", value: q });
    if (status !== "all") list.push({ field: "status", operator: "eq", value: status });
    return list;
  }, [q, status]);

  const { result, query } = useList<RepoRow>({
    resource: "repos",
    pagination: { currentPage: page, pageSize: PAGE_SIZE },
    filters,
  });

  const rows = result.data;
  const total = result.total ?? 0;
  const totalPages = Math.max(1, Math.ceil(total / PAGE_SIZE));

  const handleAction = async () => {
    if (!pending) return;
    const { row, action } = pending;
    try {
      await repoStateAction(row.id, action);
    } catch (e) {
      setActionError(`${ACTION_LABEL[action]}失败：${(e as Error).message}`);
      throw e;
    }
    setActionError(null);
    await query.refetch().catch(() => undefined);
  };

  return (
    <section className="space-y-4">
      <h2 className="font-mono text-lg text-ink">仓库管理</h2>

      {actionError && <p className="text-sm text-danger">{actionError}</p>}

      <form
        className="flex flex-wrap items-center gap-2"
        onSubmit={(e) => {
          e.preventDefault();
          setPage(1);
          setQ(search.trim());
        }}
      >
        <Input
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          placeholder="搜索仓库名"
          aria-label="仓库名搜索"
          className="w-56 border-line"
        />
        <Button type="submit" variant="outline" className="border-line text-ink-2">
          搜索
        </Button>
        <Select
          value={status}
          onValueChange={(v) => {
            setStatus(v);
            setPage(1);
          }}
        >
          <SelectTrigger className="w-36 border-line" aria-label="状态筛选">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="all">全部</SelectItem>
            <SelectItem value="published">published</SelectItem>
            <SelectItem value="pending_claim">pending_claim</SelectItem>
            <SelectItem value="delisted">delisted</SelectItem>
          </SelectContent>
        </Select>
      </form>

      <div className="rounded-lg border border-line bg-surface">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead className="text-ink-3">ID</TableHead>
              <TableHead className="text-ink-3">仓库</TableHead>
              <TableHead className="text-ink-3">语言</TableHead>
              <TableHead className="text-ink-3">星标</TableHead>
              <TableHead className="text-ink-3">来源</TableHead>
              <TableHead className="text-ink-3">状态</TableHead>
              <TableHead className="text-ink-3">分类</TableHead>
              <TableHead className="text-ink-3">质量</TableHead>
              <TableHead className="text-ink-3">卖点</TableHead>
              <TableHead className="text-ink-3">曝光 · 浏览</TableHead>
              <TableHead className="text-ink-3">发布时间</TableHead>
              <TableHead className="text-ink-3">操作</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {query.isPending && (
              <TableRow>
                <TableCell colSpan={12} className="py-8 text-center text-ink-3">
                  加载中…
                </TableCell>
              </TableRow>
            )}
            {query.isError && (
              <TableRow>
                <TableCell colSpan={12} className="py-8 text-center text-danger">
                  加载失败，请稍后重试。
                </TableCell>
              </TableRow>
            )}
            {!query.isPending && !query.isError && rows.length === 0 && (
              <TableRow>
                <TableCell colSpan={12} className="py-8 text-center text-ink-3">
                  暂无仓库。
                </TableCell>
              </TableRow>
            )}
            {rows.map((row) => (
              <TableRow key={row.id}>
                <TableCell className="font-mono text-ink-2">{row.id}</TableCell>
                <TableCell>
                  <div className="space-y-0.5">
                    <div className="font-mono text-ink">{row.full_name}</div>
                    <div className="font-mono text-xs text-ink-3">{row.owner_login}</div>
                  </div>
                </TableCell>
                <TableCell className="text-ink-2">{row.language ?? "—"}</TableCell>
                <TableCell className="font-mono text-ink-2">{row.stars}</TableCell>
                <TableCell className="font-mono text-xs text-ink-2">{row.source}</TableCell>
                <TableCell>
                  <RepoStatusBadge status={row.status} />
                </TableCell>
                <TableCell className="text-ink-2">{row.category}</TableCell>
                <TableCell className="font-mono text-ink-2">{row.quality}</TableCell>
                <TableCell className="max-w-48 truncate text-ink-2">
                  {row.tagline_zh || <span className="text-ink-4">—</span>}
                </TableCell>
                <TableCell className="font-mono text-xs text-ink-2">
                  {row.impression_count} · {row.repo_view_count}
                </TableCell>
                <TableCell className="font-mono text-xs text-ink-2">
                  {formatTime(row.published_at)}
                </TableCell>
                <TableCell>
                  <div className="flex flex-wrap items-center gap-1">
                    {row.status === "published" && (
                      <Button
                        type="button"
                        size="sm"
                        variant="destructive"
                        onClick={() => setPending({ row, action: "delist" })}
                      >
                        下架
                      </Button>
                    )}
                    {row.status === "delisted" && (
                      <>
                        <Button
                          type="button"
                          size="sm"
                          onClick={() => setPending({ row, action: "publish" })}
                        >
                          上架
                        </Button>
                        <Button
                          type="button"
                          size="sm"
                          variant="outline"
                          className="border-line text-ink-2"
                          onClick={() => setPending({ row, action: "restore" })}
                        >
                          恢复
                        </Button>
                      </>
                    )}
                    {row.status === "pending_claim" && (
                      <Button
                        type="button"
                        size="sm"
                        onClick={() => setPending({ row, action: "publish" })}
                      >
                        上架
                      </Button>
                    )}
                    <Button
                      type="button"
                      size="sm"
                      variant="outline"
                      className="border-line text-ink-2"
                      onClick={() => setEditing(row)}
                    >
                      编辑
                    </Button>
                  </div>
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </div>

      <div className="flex items-center justify-between">
        <span className="text-sm text-ink-3">共 {total} 个仓库</span>
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
            pending.action === "delist"
              ? `将 ${pending.row.full_name} 下架，下架后前台不可见。`
              : pending.action === "publish"
                ? `将 ${pending.row.full_name} 上架，发布后前台可见。`
                : `将 ${pending.row.full_name} 恢复为已发布。`
          }
          danger={pending.action === "delist"}
          onConfirm={handleAction}
        />
      )}

      {editing && (
        <RepoEdit
          row={editing}
          onClose={() => setEditing(null)}
          onSaved={async () => {
            await query.refetch().catch(() => undefined);
          }}
        />
      )}
    </section>
  );
}

export default RepoList;
