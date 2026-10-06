import * as React from "react";
import { useShow } from "@refinedev/core";
import { Link, useParams } from "react-router";

import {
  banUser,
  BAN_FOREVER,
  unbanUser,
  updateAdminNote,
  type UserDetail,
} from "@/api/users";
import { ConfirmDialog } from "@/components/ConfirmDialog";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { formatTime, formatUntil, UserStatusBadge } from "./UserList";

const DURATIONS = [
  { value: "1", label: "1天", days: 1 },
  { value: "7", label: "7天", days: 7 },
  { value: "30", label: "30天", days: 30 },
  { value: "forever", label: "永久", days: null },
] as const;

const KIND_LABEL: Record<string, string> = {
  visit: "浏览",
  like: "点赞",
  favorite: "收藏",
  comment: "评论",
};

export function UserShow() {
  const { id } = useParams();
  const { result: user, query } = useShow<UserDetail>({
    resource: "users",
    id,
    queryOptions: { enabled: Boolean(id) },
  });

  const [muteComment, setMuteComment] = React.useState(false);
  const [muteSubmit, setMuteSubmit] = React.useState(false);
  const [duration, setDuration] = React.useState("1");
  const [banNote, setBanNote] = React.useState("");
  const [adminNote, setAdminNote] = React.useState("");
  const [banOpen, setBanOpen] = React.useState(false);
  const [unbanOpen, setUnbanOpen] = React.useState(false);
  const [noteOpen, setNoteOpen] = React.useState(false);
  const [actionError, setActionError] = React.useState<string | null>(null);

  React.useEffect(() => {
    if (user) setAdminNote(user.admin_note ?? "");
  }, [user?.id, user?.admin_note]);

  const durationLabel = DURATIONS.find((d) => d.value === duration)?.label ?? "1天";

  const handleBan = async () => {
    const picked = DURATIONS.find((d) => d.value === duration);
    const days = picked ? picked.days : 1;
    const until =
      days == null ? BAN_FOREVER : Math.floor(Date.now() / 1000) + days * 86400;
    try {
      await banUser(id!, {
        mute_comment: muteComment,
        mute_submit: muteSubmit,
        until,
        note: banNote,
      });
    } catch (e) {
      setActionError("封禁失败，请稍后重试");
      throw e;
    }
    setActionError(null);
    await query.refetch().catch(() => undefined);
  };

  const handleUnban = async () => {
    try {
      await unbanUser(id!);
    } catch (e) {
      setActionError("解封失败，请稍后重试");
      throw e;
    }
    setActionError(null);
    await query.refetch().catch(() => undefined);
  };

  const handleSaveNote = async () => {
    try {
      await updateAdminNote(id!, adminNote);
    } catch (e) {
      setActionError("备注保存失败，请稍后重试");
      throw e;
    }
    setActionError(null);
    await query.refetch().catch(() => undefined);
  };

  if (query.isPending) {
    return <p className="text-sm text-ink-3">加载中…</p>;
  }
  if (query.isError || !user) {
    return <p className="text-sm text-danger">用户加载失败，请稍后重试。</p>;
  }

  return (
    <section className="space-y-4">
      <div className="flex items-center justify-between">
        <h2 className="font-mono text-lg text-ink">用户详情</h2>
        <Button asChild variant="outline" size="sm" className="border-line text-ink-2">
          <Link to="/users">返回列表</Link>
        </Button>
      </div>

      {actionError && <p className="text-sm text-danger">{actionError}</p>}

      <div className="rounded-lg border border-line bg-surface p-6">
        <div className="flex items-center gap-3">
          {user.avatar_url ? (
            <img
              src={user.avatar_url}
              alt=""
              className="h-12 w-12 rounded-full border border-line"
            />
          ) : (
            <span className="flex h-12 w-12 items-center justify-center rounded-full bg-tint font-mono text-ink-2">
              {user.login.slice(0, 1).toUpperCase()}
            </span>
          )}
          <div>
            <div className="flex items-center gap-2">
              <span className="font-mono text-lg text-ink">{user.login}</span>
              <UserStatusBadge status={user.status} />
            </div>
            <p className="mt-1 text-sm text-ink-3">
              ID <span className="font-mono text-ink-2">{user.id}</span> · 注册于{" "}
              <span className="font-mono text-ink-2">{formatTime(user.created_at)}</span>
            </p>
          </div>
        </div>
        <p className="mt-4 text-sm text-ink-2">
          互动：赞 <span className="font-mono">{user.counts.likes}</span> · 藏{" "}
          <span className="font-mono">{user.counts.favorites}</span> · 访{" "}
          <span className="font-mono">{user.counts.visits}</span> · 评{" "}
          <span className="font-mono">{user.counts.comments}</span>
        </p>
      </div>

      <div className="rounded-lg border border-line bg-surface p-6">
        <h3 className="font-mono text-sm text-ink-2">封禁信息</h3>
        <dl className="mt-3 space-y-2 text-sm">
          <div className="flex gap-2">
            <dt className="w-24 text-ink-3">禁言截止</dt>
            <dd className="font-mono text-ink">{formatUntil(user.ban_comment_until)}</dd>
          </div>
          <div className="flex gap-2">
            <dt className="w-24 text-ink-3">禁投稿截止</dt>
            <dd className="font-mono text-ink">{formatUntil(user.ban_submit_until)}</dd>
          </div>
          <div className="flex gap-2">
            <dt className="w-24 text-ink-3">封禁备注</dt>
            <dd className="text-ink">{user.ban_note || "—"}</dd>
          </div>
        </dl>
      </div>

      <div className="rounded-lg border border-line bg-surface p-6">
        <h3 className="font-mono text-sm text-ink-2">最后活跃</h3>
        {user.recent_interactions.length === 0 ? (
          <p className="mt-2 text-sm text-ink-3">暂无互动记录。</p>
        ) : (
          <ul className="mt-2 space-y-1 text-sm text-ink-2">
            {user.recent_interactions.map((item, i) => (
              <li key={`${item.repo_id}-${item.created_at}-${i}`} className="flex gap-2">
                <span className="font-mono text-ink-2">{formatTime(item.created_at)}</span>
                <span>{KIND_LABEL[item.kind] ?? item.kind}</span>
                <span className="font-mono text-ink-3">仓库 #{item.repo_id}</span>
              </li>
            ))}
          </ul>
        )}
      </div>

      <div className="rounded-lg border border-line bg-surface p-6">
        <h3 className="font-mono text-sm text-ink-2">管理备注</h3>
        <div className="mt-3 flex items-end gap-2">
          <div className="flex-1">
            <Label htmlFor="admin-note" className="text-ink-3">
              管理备注
            </Label>
            <Input
              id="admin-note"
              value={adminNote}
              maxLength={2000}
              onChange={(e) => setAdminNote(e.target.value)}
              className="mt-1.5 border-line"
            />
          </div>
          <Button type="button" variant="outline" className="border-line text-ink-2" onClick={() => setNoteOpen(true)}>
            保存备注
          </Button>
        </div>
      </div>

      <div className="rounded-lg border border-line bg-surface p-6">
        <h3 className="font-mono text-sm text-ink-2">封禁面板</h3>
        <div className="mt-3 flex flex-wrap items-center gap-6">
          <div className="flex items-center gap-2">
            <input
              id="mute-comment"
              type="checkbox"
              checked={muteComment}
              onChange={(e) => setMuteComment(e.target.checked)}
              className="h-4 w-4 accent-brand"
            />
            <Label htmlFor="mute-comment" className="text-ink">
              禁言
            </Label>
          </div>
          <div className="flex items-center gap-2">
            <input
              id="mute-submit"
              type="checkbox"
              checked={muteSubmit}
              onChange={(e) => setMuteSubmit(e.target.checked)}
              className="h-4 w-4 accent-brand"
            />
            <Label htmlFor="mute-submit" className="text-ink">
              禁投稿
            </Label>
          </div>
          <div className="flex items-center gap-2">
            <Label className="text-ink-3">时长</Label>
            <Select value={duration} onValueChange={setDuration}>
              <SelectTrigger className="w-28 border-line" aria-label="时长">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {DURATIONS.map((d) => (
                  <SelectItem key={d.value} value={d.value}>
                    {d.label}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
          <div className="flex items-center gap-2">
            <Label htmlFor="ban-note" className="text-ink-3">
              处罚备注
            </Label>
            <Input
              id="ban-note"
              value={banNote}
              maxLength={500}
              onChange={(e) => setBanNote(e.target.value)}
              className="w-56 border-line"
            />
          </div>
        </div>
        <div className="mt-4 flex gap-2">
          <Button type="button" onClick={() => setBanOpen(true)}>
            封禁
          </Button>
          {user.status === "banned" && (
            <Button
              type="button"
              variant="destructive"
              onClick={() => setUnbanOpen(true)}
            >
              解封
            </Button>
          )}
        </div>
      </div>

      <ConfirmDialog
        open={banOpen}
        onOpenChange={setBanOpen}
        title="确认封禁"
        description={`禁言：${muteComment ? "是" : "否"} · 禁投稿：${
          muteSubmit ? "是" : "否"
        } · 时长：${durationLabel} · 备注：${banNote || "无"}`}
        danger
        onConfirm={handleBan}
      />
      <ConfirmDialog
        open={unbanOpen}
        onOpenChange={setUnbanOpen}
        title="确认解封"
        description={`将解除 ${user.login} 的全部封禁并清除封禁备注。`}
        danger
        onConfirm={handleUnban}
      />
      <ConfirmDialog
        open={noteOpen}
        onOpenChange={setNoteOpen}
        title="保存管理备注"
        description={`将 ${user.login} 的管理备注保存为：${adminNote || "（空）"}`}
        onConfirm={handleSaveNote}
      />
    </section>
  );
}

export default UserShow;
