import * as React from "react";
import { Link } from "react-router";

import {
  getFeedback, type FeedbackCategory, type FeedbackRow, type FeedbackStatus,
} from "@/api/feedback";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { useQPrefill } from "@/hooks/useQPrefill";
import { formatTime } from "@/pages/users/UserList";

const PAGE_SIZE = 20;

const CATEGORY_LABEL: Record<FeedbackCategory, { text: string; cls: string }> = {
  bug: { text: "问题反馈", cls: "text-danger" },
  suggest: { text: "建议", cls: "text-brand" },
  other: { text: "其他", cls: "text-ink-3" },
};

export function FeedbackStatusBadge({ status }: { status: FeedbackStatus }) {
  const cls = status === "pending" ? "text-warn" : status === "done" ? "text-ok" : "text-ink-2";
  const text = status === "pending" ? "待处理" : status === "done" ? "已处理" : "已忽略";
  return (
    <Badge variant="outline" className={`border-line font-mono ${cls}`}>{text}</Badge>
  );
}

export function FeedbackCategoryBadge({ category }: { category: FeedbackCategory }) {
  const { text, cls } = CATEGORY_LABEL[category];
  return <Badge variant="outline" className={`border-line font-mono ${cls}`}>{text}</Badge>;
}

export function FeedbackInbox() {
  const [search, setSearch] = React.useState("");
  const [q, setQ] = React.useState("");
  const [status, setStatus] = React.useState("all");
  const [category, setCategory] = React.useState("all");
  const [page, setPage] = React.useState(1);
  const [rows, setRows] = React.useState<FeedbackRow[]>([]);
  const [total, setTotal] = React.useState(0);
  const [state, setState] = React.useState<"loading" | "error" | "ready">("loading");

  useQPrefill((urlQ) => { setSearch(urlQ); setQ(urlQ); });

  React.useEffect(() => {
    let alive = true;
    setState("loading");
    getFeedback({
      q: q || undefined,
      status: status === "all" ? undefined : status,
      category: category === "all" ? undefined : category,
      page,
      page_size: PAGE_SIZE,
    })
      .then((r) => {
        if (!alive) return;
        setRows(r.data);
        setTotal(r.total);
        setState("ready");
      })
      .catch(() => alive && setState("error"));
    return () => { alive = false; };
  }, [q, status, category, page]);

  const totalPages = Math.max(1, Math.ceil(total / PAGE_SIZE));

  return (
    <section className="space-y-4">
      <h2 className="font-mono text-lg text-ink">反馈收件箱</h2>

      <form
        className="flex flex-wrap items-center gap-2"
        onSubmit={(e) => {
          e.preventDefault();
          setQ(search.trim());
          setPage(1);
        }}
      >
        {/* maxLength 对齐服务端 q 上限 50，防超长关键词 422 落进「加载失败」误报 */}
        <Input value={search} onChange={(e) => setSearch(e.target.value)} maxLength={50}
          placeholder="内容关键词" aria-label="内容关键词" className="w-56 border-line" />
        <Button type="submit" variant="outline" className="border-line text-ink-2">筛选</Button>
        <Select value={status} onValueChange={(v) => { setStatus(v); setPage(1); }}>
          <SelectTrigger className="w-32 border-line" aria-label="状态筛选"><SelectValue /></SelectTrigger>
          <SelectContent>
            <SelectItem value="all">全部状态</SelectItem>
            <SelectItem value="pending">待处理</SelectItem>
            <SelectItem value="done">已处理</SelectItem>
            <SelectItem value="ignored">已忽略</SelectItem>
          </SelectContent>
        </Select>
        <Select value={category} onValueChange={(v) => { setCategory(v); setPage(1); }}>
          <SelectTrigger className="w-32 border-line" aria-label="分类筛选"><SelectValue /></SelectTrigger>
          <SelectContent>
            <SelectItem value="all">全部分类</SelectItem>
            <SelectItem value="bug">问题反馈</SelectItem>
            <SelectItem value="suggest">建议</SelectItem>
            <SelectItem value="other">其他</SelectItem>
          </SelectContent>
        </Select>
      </form>

      <div className="rounded-lg border border-line bg-surface">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead className="text-ink-3">ID</TableHead>
              <TableHead className="text-ink-3">用户</TableHead>
              <TableHead className="text-ink-3">分类</TableHead>
              <TableHead className="text-ink-3">状态</TableHead>
              <TableHead className="text-ink-3">内容</TableHead>
              <TableHead className="text-ink-3">回复</TableHead>
              <TableHead className="text-ink-3">时间</TableHead>
              <TableHead className="text-ink-3">操作</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {state === "loading" && (
              <TableRow><TableCell colSpan={8} className="py-8 text-center text-ink-3">加载中…</TableCell></TableRow>
            )}
            {state === "error" && (
              <TableRow><TableCell colSpan={8} className="py-8 text-center text-danger">加载失败，请稍后重试。</TableCell></TableRow>
            )}
            {state === "ready" && rows.length === 0 && (
              <TableRow><TableCell colSpan={8} className="py-8 text-center text-ink-3">暂无反馈。</TableCell></TableRow>
            )}
            {state === "ready" && rows.map((r) => (
              <TableRow key={r.id}>
                <TableCell className="font-mono text-ink-2">{r.id}</TableCell>
                <TableCell className="font-mono text-ink-2">{r.user_login}</TableCell>
                <TableCell><FeedbackCategoryBadge category={r.category} /></TableCell>
                <TableCell><FeedbackStatusBadge status={r.status} /></TableCell>
                <TableCell className="max-w-64 truncate text-ink-2">{r.body}</TableCell>
                <TableCell className="font-mono text-ink-2">{r.reply_count}</TableCell>
                <TableCell className="font-mono text-xs text-ink-2">{formatTime(r.created_at)}</TableCell>
                <TableCell>
                  <Button asChild variant="outline" size="sm" className="border-line text-ink-2">
                    <Link to={`/feedback/show/${r.id}`}>查看</Link>
                  </Button>
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </div>

      <div className="flex items-center justify-between">
        <span className="text-sm text-ink-3">共 {total} 条反馈</span>
        <div className="flex items-center gap-2">
          <Button type="button" variant="outline" size="sm" className="border-line text-ink-2"
            disabled={page <= 1 || state !== "ready"} onClick={() => setPage((p) => Math.max(1, p - 1))}>
            上一页
          </Button>
          <span className="font-mono text-sm text-ink-2">{page} / {totalPages}</span>
          <Button type="button" variant="outline" size="sm" className="border-line text-ink-2"
            disabled={page >= totalPages || state !== "ready"} onClick={() => setPage((p) => p + 1)}>
            下一页
          </Button>
        </div>
      </div>
    </section>
  );
}

export default FeedbackInbox;
