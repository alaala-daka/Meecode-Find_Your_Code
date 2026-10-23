// src/components/FilterPanel.tsx —— 「⚙ 筛选」触发器 + 草稿-应用两段式面板（spec §3.3）
// 桌面：触发器下方下拉面板；手机（≤720px）：底部半屏抽屉。Esc/外部点击/取消关闭并丢弃草稿。
import { useEffect, useRef, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { api } from '../api/client'
import type { Facets } from '../api/types'
import {
  activeFilterCount, parseFilters, STAR_PRESETS, SINCE_OPTIONS, writeFilters, type RepoFilters,
} from '../lib/repoFilters'
import { useIsMobile } from '../utils/useIsMobile'
import './FilterPanel.css'

const LANG_VISIBLE = 8
const TOPIC_VISIBLE = 6

export default function FilterPanel() {
  const [params, setParams] = useSearchParams()
  const [open, setOpen] = useState(false)
  const [draft, setDraft] = useState<RepoFilters>({})
  const [facets, setFacets] = useState<Facets>({ languages: [], topics: [] })
  const [langMore, setLangMore] = useState(false)
  const [topicQuery, setTopicQuery] = useState('')
  const [customStars, setCustomStars] = useState(false)
  const [customStarsMin, setCustomStarsMin] = useState('')
  const [customStarsMax, setCustomStarsMax] = useState('')
  const wrapRef = useRef<HTMLDivElement>(null)
  const isMobile = useIsMobile()

  const filters = parseFilters(params)
  const count = activeFilterCount(filters)

  function openPanel() {
    setDraft(parseFilters(params))
    setCustomStars(false)
    setCustomStarsMin('')
    setCustomStarsMax('')
    setTopicQuery('')
    setOpen(true)
  }

  // 外部点击 / Esc 关闭（草稿丢弃）；沿用 CategoryBar「更多」菜单同款模式
  useEffect(() => {
    if (!open) return
    function onDoc(e: MouseEvent) {
      if (!(e.target as HTMLElement).closest('.filter-wrap')) setOpen(false)
    }
    function onKey(e: KeyboardEvent) {
      if (e.key === 'Escape') setOpen(false)
    }
    document.addEventListener('click', onDoc)
    document.addEventListener('keydown', onKey)
    return () => {
      document.removeEventListener('click', onDoc)
      document.removeEventListener('keydown', onKey)
    }
  }, [open])

  useEffect(() => {
    if (!open) return
    api.facets().then(setFacets).catch(() => setFacets({ languages: [], topics: [] }))
  }, [open])

  function toggleTopic(t: string) {
    setDraft((d) => {
      const cur = d.topics ?? []
      if (cur.includes(t)) return { ...d, topics: cur.filter((x) => x !== t) }
      if (cur.length >= 5) return d   // 上限 5（spec §3.1）
      return { ...d, topics: [...cur, t] }
    })
  }

  function apply() {
    const next: RepoFilters = { ...draft }
    if (customStars) {
      const min = Number(customStarsMin)
      const max = Number(customStarsMax)
      if (customStarsMin.trim() !== '' && Number.isInteger(min) && min >= 0) next.stars = min
      else delete next.stars
      if (customStarsMax.trim() !== '' && Number.isInteger(max) && max >= 0) next.starsMax = max
      else delete next.starsMax
    }
    const p = new URLSearchParams(params)
    writeFilters(p, next)   // 内部已重置 page
    setParams(p)            // push：浏览器回退可撤销本次筛选
    setOpen(false)
  }

  const topicChips = facets.topics.filter((t) => t.name.includes(topicQuery.trim().toLowerCase()))
  const langChips = langMore ? facets.languages : facets.languages.slice(0, LANG_VISIBLE)

  return (
    <div className="filter-wrap" ref={wrapRef}>
      <button
        type="button"
        className={`filter-trigger ${count > 0 ? 'is-active' : ''}`}
        aria-expanded={open}
        aria-haspopup="dialog"
        onClick={() => (open ? setOpen(false) : openPanel())}
      >
        <span aria-hidden="true">⚙</span> 筛选
        {count > 0 && <span className="filter-badge">{count}</span>}
      </button>
      {open && isMobile && <div className="filter-mask" />}
      {open && (
        <div
          className={`filter-panel ${isMobile ? 'filter-panel--sheet' : ''}`}
          role="dialog"
          aria-label="精确筛选"
        >
          <div className="filter-head">
            <strong>精确筛选</strong>
            <button type="button" className="filter-clear"
              onClick={() => { setDraft({}); setCustomStars(false); setCustomStarsMin(''); setCustomStarsMax('') }}>
              清除全部
            </button>
          </div>

          <div className="filter-group">
            <div className="filter-label" id="filter-lang-label">语言</div>
            <div className="filter-chips" role="group" aria-labelledby="filter-lang-label">
              {langChips.map((l) => (
                <button key={l.name} type="button"
                  className={`filter-chip ${draft.lang === l.name ? 'is-active' : ''}`}
                  aria-pressed={draft.lang === l.name}
                  onClick={() => setDraft((d) => ({ ...d, lang: d.lang === l.name ? undefined : l.name }))}>
                  {l.name}
                </button>
              ))}
              {facets.languages.length > LANG_VISIBLE && (
                <button type="button" className="filter-chip filter-chip--more"
                  onClick={() => setLangMore((v) => !v)}>
                  {langMore ? '收起 ▴' : '更多 ▾'}
                </button>
              )}
            </div>
          </div>

          <div className="filter-group">
            <div className="filter-label" id="filter-stars-label">星数</div>
            <div className="filter-chips" role="group" aria-labelledby="filter-stars-label">
              <button type="button"
                className={`filter-chip ${draft.stars === undefined && !customStars ? 'is-active' : ''}`}
                onClick={() => { setDraft((d) => ({ ...d, stars: undefined, starsMax: undefined })); setCustomStars(false) }}>
                不限
              </button>
              {STAR_PRESETS.map((n) => (
                <button key={n} type="button"
                  className={`filter-chip ${draft.stars === n && !customStars ? 'is-active' : ''}`}
                  aria-pressed={draft.stars === n}
                  onClick={() => { setDraft((d) => ({ ...d, stars: n, starsMax: undefined })); setCustomStars(false) }}>
                  {n >= 1000 ? `≥ ${n / 1000}k` : `≥ ${n}`}
                </button>
              ))}
              <button type="button"
                className={`filter-chip filter-chip--more ${customStars ? 'is-active' : ''}`}
                onClick={() => setCustomStars(true)}>
                自定义…
              </button>
            </div>
            {customStars && (
              <div className="filter-custom">
                <label className="filter-custom-label" htmlFor="filter-stars-min">最少星数</label>
                <input id="filter-stars-min" className="filter-input" inputMode="numeric"
                  value={customStarsMin} onChange={(e) => setCustomStarsMin(e.target.value)}
                  placeholder="如 123" />
                <label className="filter-custom-label" htmlFor="filter-stars-max">最多星数</label>
                <input id="filter-stars-max" className="filter-input" inputMode="numeric"
                  value={customStarsMax} onChange={(e) => setCustomStarsMax(e.target.value)}
                  placeholder="可空" />
              </div>
            )}
          </div>

          <div className="filter-group">
            <div className="filter-label" id="filter-since-label">时间范围（按最近更新时间）</div>
            <div className="filter-chips" role="group" aria-labelledby="filter-since-label">
              <button type="button"
                className={`filter-chip ${draft.since === undefined ? 'is-active' : ''}`}
                onClick={() => setDraft((d) => ({ ...d, since: undefined }))}>
                不限
              </button>
              {SINCE_OPTIONS.map((s) => (
                <button key={s.key} type="button"
                  className={`filter-chip ${draft.since === s.key ? 'is-active' : ''}`}
                  aria-pressed={draft.since === s.key}
                  onClick={() => setDraft((d) => ({ ...d, since: d.since === s.key ? undefined : s.key }))}>
                  {s.label}
                </button>
              ))}
            </div>
          </div>

          <div className="filter-group">
            <div className="filter-label" id="filter-topic-label">Topics（多选，取交集，最多 5 个）</div>
            <input className="filter-input" type="search" placeholder="搜索 topics…"
              aria-label="搜索 topics" value={topicQuery}
              onChange={(e) => setTopicQuery(e.target.value)} />
            <div className="filter-chips" role="group" aria-labelledby="filter-topic-label">
              {topicChips.slice(0, TOPIC_VISIBLE).map((t) => {
                const active = (draft.topics ?? []).includes(t.name)
                return (
                  <button key={t.name} type="button"
                    className={`filter-chip ${active ? 'is-active' : ''}`}
                    aria-pressed={active}
                    onClick={() => toggleTopic(t.name)}>
                    #{t.name}
                  </button>
                )
              })}
            </div>
          </div>

          <div className="filter-foot">
            <button type="button" className="filter-btn" onClick={() => setOpen(false)}>取消</button>
            <button type="button" className="filter-btn filter-btn--brand" onClick={apply}>应用筛选</button>
          </div>
        </div>
      )}
    </div>
  )
}
