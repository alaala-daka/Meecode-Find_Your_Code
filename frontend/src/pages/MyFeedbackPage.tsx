// src/pages/MyFeedbackPage.tsx —— 我的反馈列表（行卡沿 .search-card，状态徽标沿 .source-badge 配方）
import { useCallback, useEffect, useRef, useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'

import { api } from '../api/client'
import type { FeedbackStatus, MyFeedbackItem } from '../api/types'
import Pagination from '../components/Pagination'
import EmptyState from '../components/EmptyState'
import ErrorBanner from '../components/ErrorBanner'
import { SkeletonGrid } from '../components/Skeleton'
import TopBar from '../components/TopBar'
import { formatEpoch } from '../utils/format'
import '../pages/SearchPage.css'
import './feedback.css'

const PAGE_SIZE = 20

const STATUS_LABEL: Record<FeedbackStatus, { text: string; cls: string }> = {
  pending: { text: '待处理', cls: 'mfb-badge-pending' },
  done: { text: '已处理', cls: 'mfb-badge-done' },
  ignored: { text: '已忽略', cls: 'mfb-badge-ignored' },
}

export function MyFeedbackPage() {
  const [params, setParams] = useSearchParams()
  const page = Math.max(1, Number(params.get('page')) || 1)
  const [items, setItems] = useState<MyFeedbackItem[]>([])
  const [total, setTotal] = useState(0)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const req = useRef(0)

  const load = useCallback(async () => {
    const token = ++req.current
    setLoading(true)
    setError(null)
    try {
      const r = await api.myFeedback(page, PAGE_SIZE)
      if (token !== req.current) return
      setItems(r.items)
      setTotal(r.total)
    } catch (e) {
      if (token !== req.current) return
      setItems([])
      setTotal(0)
      setError(e instanceof Error ? e.message : '加载失败，请重试')
    } finally {
      if (token === req.current) setLoading(false)
    }
  }, [page])

  useEffect(() => { void load() }, [load])

  const goPage = (n: number) => {
    const p = new URLSearchParams(params)
    if (n <= 1) p.delete('page')
    else p.set('page', String(n))
    setParams(p)
  }

  return (
    <>
      <TopBar />
      <main id="main" className="page-shell">
        <div className="mfb-head">
          <h1 className="mfb-title">我的反馈</h1>
          <span className="mfb-count">共 {total} 条</span>
        </div>

        {error && <ErrorBanner message={error} onRetry={() => void load()} />}
        {loading && !error && <SkeletonGrid count={3} />}
        {!loading && !error && items.length === 0 && (
          <EmptyState title="还没有提交过反馈"
            actionLabel="去首页逛逛"
            onAction={() => { window.location.assign('/') }} />
        )}
        {!loading && !error && items.length > 0 && (
          <ul className="search-list">
            {items.map((f) => {
              const s = STATUS_LABEL[f.status]
              return (
                <li key={f.id} className="search-card">
                  <div className="search-info">
                    <h3 className="search-title">
                      <Link to={`/my/feedback/${f.id}`}>{f.body_preview}</Link>
                    </h3>
                    <p className="search-meta">
                      <span className={`mfb-badge ${s.cls}`}>{s.text}</span>
                      <span className="search-date">{formatEpoch(f.created_at)}</span>
                      {f.unread_count > 0 && (
                        <span className="mfb-count">{f.unread_count} 条未读回复</span>
                      )}
                    </p>
                    {f.last_reply_preview && (
                      <p className="search-tagline">最新回复：{f.last_reply_preview}</p>
                    )}
                  </div>
                </li>
              )
            })}
          </ul>
        )}
        {!error && (
          <Pagination page={page} total={total} pageSize={PAGE_SIZE} onChange={goPage} />
        )}
      </main>
    </>
  )
}

export default MyFeedbackPage
