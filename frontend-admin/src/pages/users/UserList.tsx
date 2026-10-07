import * as React from "react";
import { useList, type CrudFilter } from "@refinedev/core";
import { Link } from "react-router";

import { BAN_FOREVER, type UserRow } from "@/api/users";
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

const PAGE_SIZE = 10;

export function formatTime(sec: number | null | undefined): string {
  if (sec == null) return "—";
  return new Date(sec * 1000).toLocaleString();
}

export function formatUntil(sec: number | null | undefined): string {
  if (sec == null) return "—";
  return sec >= BAN_FOREVER ? "永久" : new Date(sec * 1000).toLocaleString();
}

export function UserStatusBadge({ status }: { status: string }) {
  return status === "banned" ? (
    <Badge variant="outline" className="border-line font-mono text-danger">
      banned
    </Badge>
  ) : (
    <Badge variant="outline" className="border-line font-mono text-ok">
      normal
    </Badge>
  );
}

export function UserList() {
  const [search, setSearch] = React.useState("");
  const [q, setQ] = React.useState("");
  const [status, setStatus] = React.useState("all");
  const [page, setPage] = React.useState(1);

  const filters: CrudFilter[] = React.useMemo(() => {
    const list: CrudFilter[] = [];
    if (q) list.push({ field: "q", operator: "contains", value: q });
    if (status !== "all") list.push({ field: "status", operator: "eq", value: status });
    return list;
  }, [q, status]);

  const { result, query } = useList<UserRow>({
    resource: "users",
    pagination: { currentPage: page, pageSize: PAGE_SIZE },
    filters,
  });

  const rows = result.data;
  const total = result.total ?? 0;
  const totalPages = Math.max(1, Math.ceil(total / PAGE_SIZE));

  return (
    <section className="space-y-4">
      <h2 className="font-mono text-lg text-ink">用户管理</h2>

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
          placeholder="搜索登录名"
          aria-label="登录名搜索"
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
          <SelectTrigger className="w-32 border-line" aria-label="状态筛选">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="all">全部状态</SelectItem>
            <SelectItem value="normal">正常</SelectItem>
            <SelectItem value="banned">封禁</SelectItem>
          </SelectContent>
        </Select>
      </form>

      <div className="rounded-lg border border-line bg-surface">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead className="text-ink-3">ID</TableHead>
              <TableHead className="text-ink-3">登录名</TableHead>
              <TableHead className="text-ink-3">状态</TableHead>
              <TableHead className="text-ink-3">注册时间</TableHead>
              <TableHead className="text-ink-3">互动</TableHead>
              <TableHead className="text-ink-3">封禁截止</TableHead>
              <TableHead className="text-ink-3">操作</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {query.isPending && (
              <TableRow>
                <TableCell colSpan={7} className="py-8 text-center text-ink-3">
                  加载中…
                </TableCell>
              </TableRow>
            )}
            {query.isError && (
              <TableRow>
                <TableCell colSpan={7} className="py-8 text-center text-danger">
                  加载失败，请稍后重试。
                </TableCell>
              </TableRow>
            )}
            {!query.isPending && !query.isError && rows.length === 0 && (
              <TableRow>
                <TableCell colSpan={7} className="py-8 text-center text-ink-3">
                  暂无用户。
                </TableCell>
              </TableRow>
            )}
            {rows.map((row) => (
              <TableRow key={row.id}>
                <TableCell className="font-mono text-ink-2">{row.id}</TableCell>
                <TableCell>
                  <div className="flex items-center gap-2">
                    {row.avatar_url ? (
                      <img src={row.avatar_url} alt="" className="h-6 w-6 rounded-full border border-line" />
                    ) : (
                      <span className="flex h-6 w-6 items-center justify-center rounded-full bg-tint font-mono text-xs text-ink-2">
                        {row.login.slice(0, 1).toUpperCase()}
                      </span>
                    )}
                    <span className="font-mono text-ink">{row.login}</span>
                  </div>
                </TableCell>
                <TableCell>
                  <UserStatusBadge status={row.status} />
                </TableCell>
                <TableCell className="font-mono text-ink-2">{formatTime(row.created_at)}</TableCell>
                <TableCell className="font-mono text-xs text-ink-2">
                  赞 {row.counts.likes} · 藏 {row.counts.favorites} · 访 {row.counts.visits} · 评{" "}
                  {row.counts.comments}
                </TableCell>
                <TableCell>
                  {(row.ban_comment_until != null || row.ban_submit_until != null) ? (
                    <div className="space-y-0.5 font-mono text-xs text-ink-2">
                      {row.ban_comment_until != null && <div>禁言 {formatUntil(row.ban_comment_until)}</div>}
                      {row.ban_submit_until != null && <div>禁投 {formatUntil(row.ban_submit_until)}</div>}
                    </div>
                  ) : (
                    <span className="text-ink-4">—</span>
                  )}
                </TableCell>
                <TableCell>
                  <Button asChild variant="outline" size="sm" className="border-line text-ink-2">
                    <Link to={`/users/show/${row.id}`}>查看</Link>
                  </Button>
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </div>

      <div className="flex items-center justify-between">
        <span className="text-sm text-ink-3">共 {total} 位用户</span>
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
    </section>
  );
}

export default UserList;
