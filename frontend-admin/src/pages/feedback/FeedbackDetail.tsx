import * as React from "react";
import { Link, useParams } from "react-router";

import {
  createFeedbackReply, getFeedbackDetail, updateFeedback,
  type FeedbackDetail as FeedbackDetailData, type FeedbackStatus,
} from "@/api/feedback";
import { ConfirmDialog } from "@/components/ConfirmDialog";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { formatTime } from "@/pages/users/UserList";
import { FeedbackCategoryBadge, FeedbackStatusBadge } from "./FeedbackInbox";

type Pending = "status" | "note" | "reply";

export function FeedbackDetail() {
  const { id } = useParams();
  const [data, setData] = React.useState<FeedbackDetailData | null>(null);
  const [status, setStatus] = React.useState<FeedbackStatus>("pending");
  const [note, setNote] = React.useState("");
  const [replyBody, setReplyBody] = React.useState("");
  const [error, setError] = React.useState<string | null>(null);
  const [notice, setNotice] = React.useState<string | null>(null);
  const [loadState, setLoadState] = React.useState<"loading" | "error" | "ready">("loading");
  const [pending, setPending] = React.useState<Pending | null>(null);

  const load = React.useCallback(async () => {
    setLoadState("loading");
    try {
      const d = await getFeedbackDetail(Number(id));
      setData(d);
      setStatus(d.status);
      setNote(d.note);
      setLoadState("ready");
    } catch {
      setLoadState("error");
    }
  }, [id]);

  React.useEffect(() => { void load(); }, [load]);

  async function run(what: Pending): Promise<void> {
    try {
      if (what === "status") await updateFeedback(Number(id), { status });
      else if (what === "note") await updateFeedback(Number(id), { note });
      else await createFeedbackReply(Number(id), replyBody.trim());
      setNotice("已保存");
      setError(null);
      setReplyBody("");
      await load();
    } catch (e) {
      setError(`${e instanceof Error ? e.message : "操作失败"}，请重试`);
      throw e; // ConfirmDialog 依赖抛错保持弹窗打开
    }
  }

  if (loadState === "loading") return <p className="text-sm text-ink-3">加载中…</p>;
  if (loadState === "error" || !data) {
    return <p role="alert" className="text-sm text-danger">反馈加载失败，请稍后重试。</p>;
  }

  const confirmTitle = pending === "status" ? "保存反馈状态"
    : pending === "note" ? "保存内部备注" : "发送回复";
  const confirmDesc = pending === "status" ? `将状态改为「${status}」。`
    : pending === "note" ? `将内部备注保存为：${(note || "（空）").slice(0, 60)}`
    : `将回复发送给 ${data.user_login}：${replyBody.trim().slice(0, 60)}`;

  return (
    <section className="space-y-4">
      <div className="flex items-center justify-between">
        <h2 className="font-mono text-lg text-ink">反馈详情 #{data.id}</h2>
        <Button asChild variant="outline" size="sm" className="border-line text-ink-2">
          <Link to="/feedback">返回列表</Link>
        </Button>
      </div>

      {error && <p role="alert" className="text-sm text-danger">{error}</p>}
      {notice && !error && <p role="status" className="text-sm text-ink-2">{notice}</p>}

      <div className="rounded-lg border border-line bg-surface p-6">
        <h3 className="font-mono text-sm text-ink-2">原文</h3>
        {/* 纯文本：UGC 禁 dangerouslySetInnerHTML（UI 约束 §5） */}
        <p className="mt-3 whitespace-pre-wrap text-sm leading-relaxed text-ink">{data.body}</p>
        <dl className="mt-4 grid grid-cols-2 gap-2 text-sm md:grid-cols-4">
          <div><dt className="text-ink-3">用户</dt>
            <dd className="font-mono text-ink">{data.user_login}</dd></div>
          <div><dt className="text-ink-3">分类</dt>
            <dd><FeedbackCategoryBadge category={data.category} /></dd></div>
          <div><dt className="text-ink-3">提交时间</dt>
            <dd className="font-mono text-ink-2">{formatTime(data.created_at)}</dd></div>
          <div><dt className="text-ink-3">联系方式</dt>
            <dd className="font-mono text-ink-2">{data.contact || "—"}</dd></div>
        </dl>
      </div>

      <div className="rounded-lg border border-line bg-surface p-6">
        <h3 className="font-mono text-sm text-ink-2">状态流转</h3>
        <div className="mt-3 flex items-end gap-2">
          <div>
            <Label className="text-ink-3">状态</Label>
            <Select value={status} onValueChange={(v) => setStatus(v as FeedbackStatus)}>
              <SelectTrigger className="mt-1.5 w-32 border-line" aria-label="状态">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="pending">待处理</SelectItem>
                <SelectItem value="done">已处理</SelectItem>
                <SelectItem value="ignored">已忽略</SelectItem>
              </SelectContent>
            </Select>
          </div>
          <div className="ml-auto"><FeedbackStatusBadge status={data.status} /></div>
          <Button variant="outline" className="border-line text-ink-2"
            disabled={status === data.status}
            onClick={() => setPending("status")}>保存状态</Button>
        </div>
      </div>

      <div className="rounded-lg border border-line bg-surface p-6">
        <h3 className="font-mono text-sm text-ink-2">内部备注</h3>
        <div className="mt-3 flex items-end gap-2">
          <div className="flex-1">
            <Label htmlFor="fb-note" className="text-ink-3">内部备注</Label>
            <Input id="fb-note" value={note} maxLength={2000}
              onChange={(e) => setNote(e.target.value)} className="mt-1.5 border-line" />
          </div>
          <Button variant="outline" className="border-line text-ink-2" disabled={note === data.note}
            onClick={() => setPending("note")}>保存备注</Button>
        </div>
      </div>

      <div className="rounded-lg border border-line bg-surface p-6">
        <h3 className="font-mono text-sm text-ink-2">回复（{data.replies.length}）</h3>
        <ul className="mt-3 space-y-3">
          {data.replies.length === 0 && <li className="text-sm text-ink-3">还没有回复。</li>}
          {data.replies.map((r) => (
            <li key={r.id} className="rounded-md border border-line bg-paper p-4">
              <p className="flex items-center gap-2 text-xs text-ink-3">
                <span className="font-mono text-ink-2">{r.author_login}</span>
                <span className="font-mono">{formatTime(r.created_at)}</span>
                {r.read_at === null && (
                  <span className="font-mono text-danger">未读</span>
                )}
              </p>
              <p className="mt-2 whitespace-pre-wrap text-sm text-ink">{r.body}</p>
            </li>
          ))}
        </ul>
        <div className="mt-4 flex items-end gap-2">
          <div className="flex-1">
            <Label htmlFor="fb-reply" className="text-ink-3">回复内容</Label>
            <Input id="fb-reply" value={replyBody} maxLength={1000}
              onChange={(e) => setReplyBody(e.target.value)} className="mt-1.5 border-line" />
          </div>
          <Button disabled={!replyBody.trim()} onClick={() => setPending("reply")}>发送回复</Button>
        </div>
      </div>

      {pending && (
        <ConfirmDialog
          open
          onOpenChange={(open) => { if (!open) setPending(null); }}
          title={confirmTitle}
          description={confirmDesc}
          error={error}
          onConfirm={() => run(pending)}
        />
      )}
    </section>
  );
}

export default FeedbackDetail;
