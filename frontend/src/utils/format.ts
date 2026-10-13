// src/utils/format.ts
/** 时间展示：<1小时「刚刚」，<24小时「x 小时前」，<7天「x 天前」，否则 MM-DD（B 站节奏） */
export function formatTime(isoTime: string, nowMs: number = Date.now()): string {
  const diff = nowMs - new Date(isoTime).getTime()
  const hour = 3600_000
  if (diff < hour) return '刚刚'
  if (diff < 24 * hour) return `${Math.floor(diff / hour)} 小时前`
  if (diff < 7 * 24 * hour) return `${Math.floor(diff / (24 * hour))} 天前`
  const d = new Date(isoTime)
  const mm = String(d.getMonth() + 1).padStart(2, '0')
  const dd = String(d.getDate()).padStart(2, '0')
  return `${mm}-${dd}`
}

/** 数字展示：≥10000 转「x.x万」（B 站节奏） */
export function formatCount(n: number): string {
  if (n >= 10000) return `${(n / 10000).toFixed(1).replace(/\.0$/, '')}万`
  return String(n)
}

/** epoch 秒 → 相对时间（后端反馈/评论时间戳口径，与 formatTime 同风格） */
export function formatEpoch(epochSec: number, nowMs: number = Date.now()): string {
  return formatTime(new Date(epochSec * 1000).toISOString(), nowMs)
}
