// src/pages/SearchPage.tsx —— 搜索结果：SkillsMP 式横向线条卡（标题高亮 + 来源行 + 卖点 + 元信息 + 分类）+ 排序 tab + 分页
import { useCallback, useEffect, useRef, useState } from 'react'
import { Link, useNavigate, useSearchParams } from 'react-router-dom'
import { api } from '../api/client'
import type { RepoCardData, SortKey } from '../api/types'
import Capsule from '../components/Capsule'
import EmptyState from '../components/EmptyState'
import ErrorBanner from '../components/ErrorBanner'
import Pagination from '../components/Pagination'
import Tabs from '../components/Tabs'
import TopBar from '../components/TopBar'
import { languageColor } from '../theme/languageColors'
import { formatCount, formatTime } from '../utils/format'
import './SearchPage.css'

const PAGE_SIZE = 8
const SORTS = [
  { key: 'default', label: '综合' },
  { key: 'newest', label: '最新' },
  { key: 'stars', label: '最多 star' },
]

function Highlight({ text, kw }: { text: string; kw: string }) {
  const i = text.toLowerCase().indexOf(kw.toLowerCase())
  if (i < 0 || !kw) return <>{text}</>
  return (
    <>
      {text.slice(0, i)}
      <mark>{text.slice(i, i + kw.length)}</mark>
      {text.slice(i + kw.length)}
    </>
  )
}

export default function SearchPage() {
  const [params, setParams] = useSearchParams()
  const navigate = useNavigate()
  const q = params.get('q') ?? ''
  const sort = (params.get('sort') as SortKey) || 'default'
  const page = Math.max(1, Number(params.get('page')) || 1)
  const [cards, setCards] = useState<RepoCardData[]>([])
  const [total, setTotal] = useState(0)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const reqRef = useRef(0) // 请求令牌：丢弃过期响应，防快速换词时旧结果覆盖

  const run = useCallback(async () => {
    if (!q) {
      setCards([])
      setTotal(0)
      setLoading(false)
      return
    }
    const req = ++reqRef.current
    setLoading(true)
    setError(null)
    try {
      const res = await api.search(q, sort, page)
      if (req !== reqRef.current) return
      setCards(res.cards)
      setTotal(res.total)
    } catch {
      if (req !== reqRef.current) return
      setCards([])
      setTotal(0)
      setError('搜索失败，请重试')
    } finally {
      if (req === reqRef.current) setLoading(false)
    }
  }, [q, sort, page])

  useEffect(() => { void run() }, [run])

  // 换词重置页码（延续"换词回第 1 页"行为，防空白死页）；仅当 q 真正变化时触发，用户翻页不受影响
  const prevQ = useRef(q)
  useEffect(() => {
    if (prevQ.current === q) return
    prevQ.current = q
    if (page !== 1) {
      const p = new URLSearchParams(params)
      p.delete('page')
      setParams(p, { replace: true })
    }
  }, [q, page, params, setParams])

  function changeSort(k: string) {
    const p = new URLSearchParams(params)
    p.set('sort', k)
    p.delete('page')
    setParams(p)
  }

  function changePage(n: number) {
    const p = new URLSearchParams(params)
    p.set('page', String(n))
    setParams(p)
  }

  return (
    <>
      <TopBar />
      <h1 className="visually-hidden">搜索「{q}」</h1>
      <main id="main" className="page-shell search-page">
        {!q && <EmptyState title="在顶栏输入关键词开始搜索" />}
        {q && (
          <>
            <p className="search-summary" aria-live="polite">搜索「{q}」· 共 {total} 个结果</p>
            <Tabs items={SORTS.map((s) => ({ key: s.key, label: s.label }))} active={sort}
              onChange={changeSort} />
          </>
        )}
        {error && <ErrorBanner message={error} onRetry={() => void run()} />}
        {loading && !error && q !== '' && <p className="search-loading">搜索中…</p>}
        {!loading && !error && q !== '' && total === 0 && (
          <EmptyState title="没有找到相关仓库，换个关键词试试" actionLabel="推广我的仓库" onAction={() => navigate('/submit')} />
        )}
        {!loading && !error && cards.length > 0 && (
          <ul className="search-list">
            {cards.map((c) => {
              const lang = languageColor(c.language)
              return (
                <li key={c.id} className="search-card" data-testid={`search-card-${c.id}`}>
                  <div className="search-info">
                    <h3 className="search-title">
                      <Link to={`/repo/${c.id}`}><Highlight text={c.title} kw={q} /></Link>
                    </h3>
                    <p className="search-path">
                      <span className="search-owner">{c.owner_login}</span>
                    </p>
                    <p className="search-tagline">{c.tagline_zh}</p>
                    <p className="search-meta">
                      <span className="search-stars">★ {formatCount(c.stars)}</span>
                      {c.language && (
                        <span className="search-lang">
                          <span className="lang-dot" style={{ backgroundColor: lang }} aria-hidden="true" />
                          {c.language}
                        </span>
                      )}
                      <span className="search-date">{formatTime(c.published_at)}</span>
                    </p>
                  </div>
                  <Capsule label={c.category} bg="var(--brand-thin)" fg="var(--brand)" />
                </li>
              )
            })}
          </ul>
        )}
        {!error && <Pagination page={page} total={total} pageSize={PAGE_SIZE} onChange={changePage} />}
      </main>
    </>
  )
}
