import * as React from "react";

import { REPO_CATEGORIES, updateRepo, type RepoRow } from "@/api/repos";
import { ConfirmDialog } from "@/components/ConfirmDialog";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";

export type RepoEditProps = {
  row: RepoRow;
  onClose: () => void;
  onSaved: () => void | Promise<void>;
};

const clampQuality = (raw: string): number | null => {
  if (raw.trim() === "") return null;
  const n = Number(raw);
  if (!Number.isFinite(n)) return null;
  return Math.min(10, Math.max(0, Math.round(n)));
};

export function RepoEdit({ row, onClose, onSaved }: RepoEditProps) {
  const [category, setCategory] = React.useState(row.category);
  const [quality, setQuality] = React.useState(String(row.quality));
  const [tagline, setTagline] = React.useState(row.tagline_zh);
  const [confirmOpen, setConfirmOpen] = React.useState(false);
  const [actionError, setActionError] = React.useState<string | null>(null);

  const categoryOptions = React.useMemo(
    () =>
      REPO_CATEGORIES.includes(row.category)
        ? REPO_CATEGORIES
        : [row.category, ...REPO_CATEGORIES],
    [row.category],
  );

  const handleSave = async () => {
    try {
      await updateRepo(row.id, {
        category,
        quality: clampQuality(quality),
        tagline_zh: tagline,
      });
    } catch (e) {
      setActionError(`保存失败：${(e as Error).message}`);
      throw e;
    }
    setActionError(null);
    await onSaved();
    onClose();
  };

  return (
    <Dialog open onOpenChange={(open) => { if (!open) onClose(); }}>
      <DialogContent className="border-line bg-surface shadow-none">
        <DialogHeader>
          <DialogTitle className="font-mono text-ink">编辑仓库元数据</DialogTitle>
          <DialogDescription className="font-mono text-ink-2">{row.full_name}</DialogDescription>
        </DialogHeader>

        {actionError && !confirmOpen && <p className="text-sm text-danger">{actionError}</p>}

        <div className="space-y-4">
          <div>
            <Label htmlFor="repo-category" className="text-ink-3">
              分类
            </Label>
            <Select value={category} onValueChange={setCategory}>
              <SelectTrigger
                id="repo-category"
                aria-label="分类"
                className="mt-1.5 w-full border-line"
              >
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {categoryOptions.map((c) => (
                  <SelectItem key={c} value={c}>
                    {c}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>

          <div>
            <Label htmlFor="repo-quality" className="text-ink-3">
              质量
            </Label>
            <Input
              id="repo-quality"
              type="number"
              min={0}
              max={10}
              value={quality}
              onChange={(e) => setQuality(e.target.value)}
              className="mt-1.5 border-line"
            />
          </div>

          <div>
            <Label htmlFor="repo-tagline" className="text-ink-3">
              卖点
            </Label>
            <Input
              id="repo-tagline"
              value={tagline}
              maxLength={200}
              onChange={(e) => setTagline(e.target.value)}
              className="mt-1.5 border-line"
            />
          </div>
        </div>

        <DialogFooter>
          <Button type="button" variant="outline" className="border-line" onClick={onClose}>
            取消
          </Button>
          <Button
            type="button"
            onClick={() => {
              setActionError(null);
              setConfirmOpen(true);
            }}
          >
            保存
          </Button>
        </DialogFooter>
      </DialogContent>

      <ConfirmDialog
        open={confirmOpen}
        onOpenChange={setConfirmOpen}
        title="保存仓库元数据"
        description={`将 ${row.full_name} 的元数据更新为：分类 ${category} · 质量 ${
          clampQuality(quality) ?? "不变"
        } · 卖点 ${tagline || "（空）"}`}
        error={actionError}
        onConfirm={handleSave}
      />
    </Dialog>
  );
}

export default RepoEdit;
