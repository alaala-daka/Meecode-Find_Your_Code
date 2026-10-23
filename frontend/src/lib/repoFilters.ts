// src/lib/repoFilters.ts —— 精确筛选 URL 参数契约（spec §3.1 白名单，前端唯一出入口）
export type SinceKey = '7d' | '30d' | '90d' | 'ytd'

export interface RepoFilters {
  lang?: string
  stars?: number
  starsMax?: number
  since?: SinceKey
  topics?: string[]
}

// 硬约束：URL 参数一旦放出即被外链固化、无法回收。白名单外的键一律不读不写。
export const FILTER_PARAM_WHITELIST = ['lang', 'stars', 'stars_max', 'since', 'topic'] as const

export const SINCE_OPTIONS: { key: SinceKey; label: string }[] = [
  { key: '7d', label: '近一周' },
  { key: '30d', label: '近一月' },
  { key: '90d', label: '近三月' },
  { key: 'ytd', label: '今年' },
]

export const STAR_PRESETS = [10, 100, 500, 1000]

const SINCE_KEYS = new Set<string>(SINCE_OPTIONS.map((s) => s.key))
const MAX_TOPICS = 5
const MAX_STARS = 10_000_000

function normTopics(list: string[]): string[] {
  const out: string[] = []
  for (const raw of list) {
    const t = raw.trim().toLowerCase()
    if (/^[a-z0-9-]{1,50}$/.test(t) && !out.includes(t)) out.push(t)
    if (out.length >= MAX_TOPICS) break
  }
  return out
}

export function parseFilters(params: URLSearchParams): RepoFilters {
  const f: RepoFilters = {}
  const lang = (params.get('lang') ?? '').trim()
  if (/^[A-Za-z0-9+#.\- ]{1,30}$/.test(lang)) f.lang = lang
  const stars = Number(params.get('stars'))
  const starsMax = Number(params.get('stars_max'))
  const hasStars = params.has('stars') && Number.isInteger(stars) && stars >= 0 && stars <= MAX_STARS
  const hasMax = params.has('stars_max') && Number.isInteger(starsMax) && starsMax >= 0 && starsMax <= MAX_STARS
  if (hasStars && (!hasMax || starsMax >= stars)) f.stars = stars
  if (hasMax && (!hasStars || starsMax >= stars)) f.starsMax = starsMax
  const since = params.get('since')
  if (since && SINCE_KEYS.has(since)) f.since = since as SinceKey
  const topics = normTopics(params.getAll('topic'))
  if (topics.length > 0) f.topics = topics
  return f
}

export function writeFilters(params: URLSearchParams, f: RepoFilters): void {
  for (const k of FILTER_PARAM_WHITELIST) params.delete(k)
  params.delete('page') // 过滤变化一律回第 1 页（spec §3.4）
  if (f.lang) params.set('lang', f.lang)
  if (f.stars !== undefined) params.set('stars', String(f.stars))
  if (f.starsMax !== undefined) params.set('stars_max', String(f.starsMax))
  if (f.since) params.set('since', f.since)
  for (const t of f.topics ?? []) params.append('topic', t)
}

export function filterQuery(f: RepoFilters): URLSearchParams {
  const q = new URLSearchParams()
  if (f.lang) q.set('lang', f.lang)
  if (f.stars !== undefined) q.set('stars', String(f.stars))
  if (f.starsMax !== undefined) q.set('stars_max', String(f.starsMax))
  if (f.since) q.set('since', f.since)
  for (const t of f.topics ?? []) q.append('topic', t)
  return q
}

export function filterKey(f: RepoFilters): string {
  // 稳定序列化（store 比对）：topics 排序后取查询串 → 顺序不敏感
  // （URL 出口顺序由 filterQuery/writeFilters 保留，仅比对键做规范化）
  const canonical = f.topics && f.topics.length > 0 ? { ...f, topics: [...f.topics].sort() } : f
  return filterQuery(canonical).toString()
}

export function activeFilterCount(f: RepoFilters): number {
  return (f.lang ? 1 : 0) + (f.stars !== undefined ? 1 : 0) + (f.starsMax !== undefined ? 1 : 0)
    + (f.since ? 1 : 0) + (f.topics?.length ?? 0)
}

export function removeFilter(f: RepoFilters, chipKey: string): RepoFilters {
  if (chipKey === 'lang') { const { lang: _drop, ...rest } = f; return rest }
  if (chipKey === 'stars') { const { stars: _drop, ...rest } = f; return rest }
  if (chipKey === 'starsMax') { const { starsMax: _drop, ...rest } = f; return rest }
  if (chipKey === 'since') { const { since: _drop, ...rest } = f; return rest }
  if (chipKey.startsWith('topic:')) {
    const t = chipKey.slice('topic:'.length)
    const topics = (f.topics ?? []).filter((x) => x !== t)
    return topics.length > 0 ? { ...f, topics } : (() => { const { topics: _d, ...rest } = f; return rest })()
  }
  return f
}

export interface FilterChip { key: string; label: string; aria: string }

export function describeFilters(f: RepoFilters): FilterChip[] {
  const chips: FilterChip[] = []
  if (f.lang) chips.push({ key: 'lang', label: f.lang, aria: `移除语言筛选 ${f.lang}` })
  if (f.stars !== undefined) chips.push({ key: 'stars', label: `★ ≥ ${f.stars}`, aria: `移除星数筛选 ≥ ${f.stars}` })
  if (f.starsMax !== undefined) chips.push({ key: 'starsMax', label: `★ ≤ ${f.starsMax}`, aria: `移除星数筛选 ≤ ${f.starsMax}` })
  if (f.since) {
    const label = SINCE_OPTIONS.find((s) => s.key === f.since)?.label ?? f.since
    chips.push({ key: 'since', label, aria: `移除时间筛选 ${label}` })
  }
  for (const t of f.topics ?? []) chips.push({ key: `topic:${t}`, label: `#${t}`, aria: `移除话题筛选 ${t}` })
  return chips
}
