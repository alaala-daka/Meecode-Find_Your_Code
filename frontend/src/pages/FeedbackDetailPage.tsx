// src/pages/FeedbackDetailPage.tsx —— 我的反馈详情：头部信息卡 + 回复串平铺；用户不可回复（spec §3.4）
import { useCallback, useEffect, useRef, useState } from 'react'
import { Link, useParams } from 'react-router-dom'

import { api } from '../api/client'
import type { FeedbackDetail } from '../api/types'
import ErrorBanner from '../components/ErrorBanner'
import TopBar from '../components/TopBar'
import { useNotificationStore } from '../store/notificationStore'
import { formatEpoch } from '../utils/format'
import '../components/CommentSection.css'
import '../components/SiteFooter.css'   // 复用 .footer-cta（返回链接；SubmitPage.tsx:12 先例）
import './SearchPage.css'               // 复用 .search-loading/.search-meta/.search-date（跨组件复用显式 import）
import './feedback.css'

const STATUS_TEXT: Record<string, string> = {
  pending: '待处理', done: '已处理', ignored: '已忽略',
}

export function FeedbackDetailPage() {
  const { id } = useParams()
  const [data, setData] = useState<FeedbackDetail | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)
  const req = useRef(0)

  const load = useCallback(async () => {
    const token = ++req.current
    setLoading(true)
    setError(null)
    try {
      const d = await api.feedback(Number(id))
      if (token !== req.current) return
      setData(d)
      // 进详情即置已读（服务端副作用），同步刷新铃铛计数
      void useNotificationStore.getState().refresh()
    } catch (e) {
      if (token !== req.current) return
      setData(null)
      setError(e instanceof Error ? e.message : '加载失败，请重试')
    } finally {
      if (token === req.current) setLoading(false)
    }
  }, [id])

  useEffect(() => { void load() }, [load])

  return (
    <>
      <TopBar />
      <main id="main" className="page-shell">
        <div className="mfb-head">
          <h1 className="mfb-title">反馈详情</h1>
          <Link className="footer-cta" to="/my/feedback">← 返回我的反馈</Link>
        </div>

        {error && <ErrorBanner message={error} onRetry={() => void load()} />}
        {!error && loading && <p className="search-loading">加载中…</p>}
        {!error && data && (
          <>
            <section className="mfb-detail-head">
              <p className="search-meta">
                <span className={`mfb-badge mfb-badge-${data.status}`}>
                  {STATUS_TEXT[data.status] ?? data.status}
                </span>
                <span className="search-date">提交于 {formatEpoch(data.created_at)}</span>
              </p>
              {/* 纯文本：反馈正文全链路禁富文本化（UI 约束反模式 §5.10） */}
              <p className="mfb-detail-body">{data.body}</p>
            </section>

            <section className="mfb-thread">
              <h2 className="mfb-thread-title">回复（{data.replies.length}）</h2>
              {data.replies.length === 0 && <p className="search-loading">管理员还没有回复</p>}
              <ul className="comment-list">
                {data.replies.map((r) => (
                  <li key={r.id} className="comment-item mfb-note">
                    <div className="comment-head">
                      <span className="comment-login">{r.author_login}</span>
                      <span className="comment-time">{formatEpoch(r.created_at)}</span>
                    </div>
                    <div className="comment-body">{r.body}</div>
                  </li>
                ))}
              </ul>
            </section>
          </>
        )}
      </main>
    </>
  )
}

export default FeedbackDetailPage
