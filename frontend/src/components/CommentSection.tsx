// src/components/CommentSection.tsx —— 内嵌评论区（spec 2026-09-24）：两层平铺 + LLM 异步预审标记
import { Fragment, useEffect, useRef, useState } from 'react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import rehypeRaw from 'rehype-raw'
import rehypeSanitize from 'rehype-sanitize'
import type { Comment } from '../api/types'
import { api } from '../api/client'
import { useAuthStore } from '../store/authStore'
import { sanitizeSchema } from '../lib/sanitizeSchema'
import './CommentSection.css'

interface Props {
  repoId: number
  canModerate: boolean
  onNeedLogin: () => void
}

const STATUS_LABEL: Record<string, string> = {
  pending: '审核中',
}

const POLL_MS = 3000

function hiddenLabel(c: Comment): { text: string; title?: string } {
  // 原因非空 = LLM 拒绝；空 = 作者/管理隐藏（spec 4.6：「未通过或已隐藏」）
  return c.moderation_reason
    ? { text: '未通过审核', title: c.moderation_reason }
    : { text: '已隐藏' }
}

export default function CommentSection({ repoId, canModerate, onNeedLogin }: Props) {
  const user = useAuthStore((s) => s.user)
  const [items, setItems] = useState<Comment[]>([])
  const [total, setTotal] = useState(0)
  const [content, setContent] = useState('')
  const [replyTo, setReplyTo] = useState<{ topId: number; login: string } | null>(null)
  const [busy, setBusy] = useState(false)
  const [actionError, setActionError] = useState('')
  const reqRef = useRef(0)

  useEffect(() => {
    const token = ++reqRef.current
    api.comments(repoId).then((page) => {
      if (token !== reqRef.current) return
      setItems(page.items)
      setTotal(page.total)
    }).catch(() => {
      if (token === reqRef.current) setActionError('评论加载失败')
    })
  }, [repoId])

  const hasPending = items.some((c) => c.status === 'pending')

  useEffect(() => {
    if (!hasPending) return
    const timer = setInterval(() => {
      const token = ++reqRef.current
      api.comments(repoId).then((page) => {
        if (token !== reqRef.current) return
        setItems(page.items)
        setTotal(page.total)
      }).catch(() => {})
    }, POLL_MS)
    return () => clearInterval(timer)
  }, [hasPending, repoId])

  const tops = items.filter((c) => c.parent_id === null)
  const repliesOf = (id: number) => items.filter((c) => c.parent_id === id)

  async function send() {
    if (!user) { onNeedLogin(); return }
    const text = content.trim()
    if (!text || busy) return
    setBusy(true)
    setActionError('')
    reqRef.current += 1
    try {
      const created = await api.postComment(repoId, text, replyTo?.topId ?? null)
      setItems((prev) => [...prev, created])
      setTotal((t) => t + (created.parent_id === null ? 1 : 0))
      setContent('')
      setReplyTo(null)
    } catch (e) {
      setActionError(e instanceof Error ? e.message : '操作失败，请重试')
    } finally {
      setBusy(false)
    }
  }

  async function remove(c: Comment) {
    const prev = items
    reqRef.current += 1
    setItems((p) => p.filter((x) => x.id !== c.id && x.parent_id !== c.id))
    try {
      await api.deleteComment(c.id)
      setTotal((t) => Math.max(0, t - (c.parent_id === null ? 1 : 0)))
    } catch {
      setItems(prev)
      setActionError('操作失败，请重试')
    }
  }

  async function hide(c: Comment) {
    const prev = items
    reqRef.current += 1
    setItems((p) => p.filter((x) => x.id !== c.id && x.parent_id !== c.id))
    try {
      await api.hideComment(c.id)
    } catch {
      setItems(prev)
      setActionError('操作失败，请重试')
    }
  }

  function renderComment(c: Comment) {
    const mine = user != null && 'id' in user && user.id === c.user_id
    const topId = c.parent_id ?? c.id
    return (
      <li key={c.id} className={`comment-item${c.parent_id !== null ? ' comment-reply' : ''}`}>
        <div className="comment-head">
          {c.user_avatar
            ? <img className="comment-avatar" src={c.user_avatar} alt="" />
            : <span className="comment-avatar comment-avatar-empty" />}
          <span className="comment-login">{c.user_login}</span>
          <span className="comment-time">{c.created_at_iso.slice(0, 10)}</span>
          {STATUS_LABEL[c.status] && <span className="comment-badge">{STATUS_LABEL[c.status]}</span>}
          {c.status === 'hidden' && (
            <span className="comment-badge" title={hiddenLabel(c).title}>{hiddenLabel(c).text}</span>
          )}
        </div>
        <div className="comment-body">
          <ReactMarkdown
            remarkPlugins={[remarkGfm]}
            rehypePlugins={[rehypeRaw, [rehypeSanitize, sanitizeSchema]]}
          >
            {c.content}
          </ReactMarkdown>
        </div>
        <div className="comment-actions">
          {c.status !== 'hidden' && (
            <button type="button" className="comment-action" onClick={() => setReplyTo({ topId, login: c.user_login })}>回复</button>
          )}
          {mine && <button type="button" className="comment-action" onClick={() => void remove(c)}>删除</button>}
          {canModerate && !mine && (
            <button type="button" className="comment-action" onClick={() => void hide(c)}>隐藏</button>
          )}
        </div>
        {replyTo?.topId === topId && c.parent_id === null && (
          <div className="comment-reply-box">
            <button
              type="button"
              className="comment-reply-cancel"
              aria-label="回到上级评论"
              title="回到上级评论"
              onClick={() => setReplyTo(null)}
            >
              <svg width="18" height="18" viewBox="0 0 24 24" fill="none" aria-hidden="true">
                <path d="M18.0702 9.57L12.0002 3.5L5.93018 9.57" stroke="currentColor" strokeWidth="1.5" strokeMiterlimit="10" strokeLinecap="round" strokeLinejoin="round" />
                <path d="M12 20.4999V3.66992" stroke="currentColor" strokeWidth="1.5" strokeMiterlimit="10" strokeLinecap="round" strokeLinejoin="round" />
              </svg>
            </button>
            <textarea
              value={content}
              onChange={(e) => setContent(e.target.value)}
              placeholder={`回复 @${replyTo.login}：`}
              rows={3}
            />
            <button type="button" className="comment-send" onClick={() => void send()} disabled={busy}>发送</button>
          </div>
        )}
      </li>
    )
  }

  return (
    <section className="comment-section">
      <h2 className="comment-title">讨论 <span className="comment-count">{total}</span></h2>
      {actionError && <p className="comment-error">{actionError}</p>}
      <ul className="comment-list">
        {tops.map((t) => (
          <Fragment key={t.id}>
            {renderComment(t)}
            {repliesOf(t.id).map((r) => renderComment(r))}
          </Fragment>
        ))}
      </ul>
      {!replyTo && (
        <div className="comment-form">
          <textarea
            value={content}
            onChange={(e) => setContent(e.target.value)}
            placeholder={user ? '写下你的评论…' : '登录后参与讨论'}
            rows={3}
          />
          <button type="button" className="comment-send" onClick={() => void send()} disabled={busy}>发送</button>
        </div>
      )}
    </section>
  )
}
