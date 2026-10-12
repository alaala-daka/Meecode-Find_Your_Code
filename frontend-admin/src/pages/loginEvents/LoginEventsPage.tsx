import * as React from "react";

import { getLoginEvents, type LoginEventRow } from "@/api/loginEvents";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from "@/components/ui/select";
import {
  Table, TableBody, TableCell, TableHead, TableHeader, TableRow,
} from "@/components/ui/table";
import { formatTime } from "@/pages/users/UserList";

const PAGE_SIZE = 20;
const IP_HASH_TRUNC = 12;

export function EventBadge({ event }: { event: "login" | "logout" }) {
  return (
    <Badge variant="outline" className="border-line font-mono text-ink-2">
      {event === "login" ? "登录" : "登出"}
    </Badge>
  );
}

export function OkBadge({ ok }: { ok: 0 | 1 }) {
  return ok === 1 ? (
    <Badge variant="outline" className="border-line font-mono text-ok">成功</Badge>
  ) : (
    <Badge variant="outline" className="border-line font-mono text-danger">失败</Badge>
  );
}

export function LoginEventsPage() {
  const [search, setSearch] = React.useState("");
  const [q, setQ] = React.useState("");
  const [ok, setOk] = React.useState("all");
  const [event, setEvent] = React.useState("all");
  const [from, setFrom] = React.useState("");
  const [to, setTo] = React.useState("");
  const [ip, setIp] = React.useState("");
  const [page, setPage] = React.useState(1);
  const [rows, setRows] = React.useState<LoginEventRow[]>([]);
  const [total, setTotal] = React.useState(0);
  const [state, setState] = React.useState<"loading" | "error" | "ready">("loading");
  const [lookupFor, setLookupFor] = React.useState<string | null>(null);
  const [lookupIp, setLookupIp] = React.useState("");

  React.useEffect(() => {
    let alive = true;
    setState("loading");
    getLoginEvents({
      q, ok: ok === "all" ? undefined : ok,
      event: event === "all" ? undefined : event,
      from: from || undefined, to: to || undefined,
      ip: ip || undefined, page, page_size: PAGE_SIZE,
    })
      .then((r) => {
        if (!alive) return;
        setRows(r.data);
        setTotal(r.total);
        setState("ready");
      })
      .catch(() => alive && setState("error"));
    return () => { alive = false; };
  }, [q, ok, event, from, to, ip, page]);

  const totalPages = Math.max(1, Math.ceil(total / PAGE_SIZE));

  return (
    <section className="space-y-4">
      <h2 className="font-mono text-lg text-ink">登录日志</h2>
      <form
        className="flex flex-wrap items-center gap-2"
        onSubmit={(e) => {
          e.preventDefault();
          setQ(search.trim());
          setIp("");
          setPage(1);
        }}
      >
        <Input
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          placeholder="登录名模糊"
          className="w-40 border-line"
        />
        <Select value={ok} onValueChange={(v) => { setOk(v); setPage(1); }}>
          <SelectTrigger className="w-28 border-line"><SelectValue /></SelectTrigger>
          <SelectContent>
            <SelectItem value="all">全部成败</SelectItem>
            <SelectItem value="1">成功</SelectItem>
            <SelectItem value="0">失败</SelectItem>
          </SelectContent>
        </Select>
        <Select value={event} onValueChange={(v) => { setEvent(v); setPage(1); }}>
          <SelectTrigger className="w-28 border-line"><SelectValue /></SelectTrigger>
          <SelectContent>
            <SelectItem value="all">全部事件</SelectItem>
            <SelectItem value="login">登录</SelectItem>
            <SelectItem value="logout">登出</SelectItem>
          </SelectContent>
        </Select>
        <Input type="date" value={from} onChange={(e) => { setFrom(e.target.value); setPage(1); }}
          className="w-36 border-line" aria-label="开始日期" />
        <Input type="date" value={to} onChange={(e) => { setTo(e.target.value); setPage(1); }}
          className="w-36 border-line" aria-label="结束日期" />
        <Button type="submit" variant="outline" className="border-line text-ink-2">查询</Button>
        {ip && (
          <Button type="button" variant="outline" className="border-line text-ink-2"
            onClick={() => { setIp(""); setPage(1); }}>
            清除 IP 反查
          </Button>
        )}
      </form>

      <div className="rounded-lg border border-line bg-surface">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead className="text-ink-3">时间</TableHead>
              <TableHead className="text-ink-3">login</TableHead>
              <TableHead className="text-ink-3">事件</TableHead>
              <TableHead className="text-ink-3">成败</TableHead>
              <TableHead className="text-ink-3">ip_hash</TableHead>
              <TableHead className="text-ink-3">操作</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {state === "loading" && (
              <TableRow><TableCell colSpan={6} role="status" className="py-8 text-center text-ink-3">加载中…</TableCell></TableRow>
            )}
            {state === "error" && (
              <TableRow><TableCell colSpan={6} role="alert" className="py-8 text-center text-danger">加载失败</TableCell></TableRow>
            )}
            {state === "ready" && rows.length === 0 && (
              <TableRow><TableCell colSpan={6} className="py-8 text-center text-ink-3">暂无登录日志</TableCell></TableRow>
            )}
            {state === "ready" && rows.map((r) => (
              <TableRow key={r.id}>
                <TableCell className="font-mono text-xs text-ink-2">{formatTime(r.ts)}</TableCell>
                <TableCell className="font-mono text-ink-2">{r.login || "—"}</TableCell>
                <TableCell><EventBadge event={r.event} /></TableCell>
                <TableCell><OkBadge ok={r.ok} /></TableCell>
                <TableCell className="font-mono text-xs text-ink-2">{r.ip_hash ? r.ip_hash.slice(0, IP_HASH_TRUNC) : "—"}</TableCell>
                <TableCell>
                  <Button type="button" variant="outline" size="sm"
                    className="border-line text-ink-2"
                    onClick={() => { setLookupFor(r.ip_hash); setLookupIp(""); }}>
                    反查
                  </Button>
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
        <div className="flex items-center justify-between px-4 py-3">
          <span className="text-sm text-ink-3">共 {total} 条</span>
          <div className="flex items-center gap-2">
            <Button type="button" variant="outline" size="sm" className="border-line text-ink-2"
              onClick={() => setPage((p) => Math.max(1, p - 1))}>上一页</Button>
            <span className="font-mono text-sm text-ink-2">{page} / {totalPages}</span>
            <Button type="button" variant="outline" size="sm" className="border-line text-ink-2"
              onClick={() => setPage((p) => Math.min(totalPages, p + 1))}>下一页</Button>
          </div>
        </div>
      </div>

      <Dialog open={lookupFor !== null} onOpenChange={(o) => !o && setLookupFor(null)}>
        <DialogContent className="border-line bg-surface shadow-none">
          <DialogHeader>
            <DialogTitle>IP 精确反查</DialogTitle>
            <DialogDescription>
              输入完整 IP（IPv6 可用任意等价写法），查同 IP 全部行为。
            </DialogDescription>
          </DialogHeader>
          <div className="space-y-2">
            <Label htmlFor="lookup-ip" className="text-ink-3">完整 IP</Label>
            <Input id="lookup-ip" value={lookupIp}
              onChange={(e) => setLookupIp(e.target.value)} className="border-line" />
          </div>
          <DialogFooter>
            <Button type="button" variant="outline" className="border-line text-ink-2"
              onClick={() => setLookupFor(null)}>取消</Button>
            <Button type="button" onClick={() => {
              setIp(lookupIp.trim());
              setQ("");
              setSearch("");
              setPage(1);
              setLookupFor(null);
            }}>反查提交</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </section>
  );
}

export default LoginEventsPage;
