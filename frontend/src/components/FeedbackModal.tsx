// src/components/FeedbackModal.tsx —— 反馈提交弹窗（照 LoginModal：焦点圈定/Tab 循环/Esc/滚动锁/焦点归还）
import { useEffect, useRef, useState } from 'react'

import { api } from '../api/client'
import type { FeedbackCategory } from '../api/types'
import { useAuthStore } from '../store/authStore'
import Button from './Button'
import LoginModal from './LoginModal'
import './CategoryBar.css'   // 复用 .cat-pill 胶囊（SubmitPage.tsx:12 先例）
import './FeedbackModal.css'

const BODY_MAX = 500
const CONTACT_MAX = 100
const FOCUSABLE = 'button, input, textarea, select, a[href]'

const CATEGORIES: { value: FeedbackCategory; label: string }[] = [
  { value: 'bug', label: '问题反馈' },
  { value: 'suggest', label: '建议' },
  { value: 'other', label: '其他' },
]

export function FeedbackModal({ open, onClose, onSubmitted }: {
  open: boolean
  onClose: () => void
  onSubmitted?: () => void
}) {
  const user = useAuthStore((s) => s.user)
  const [category, setCategory] = useState<FeedbackCategory>('bug')
  const [body, setBody] = useState('')
  const [contact, setContact] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const panelRef = useRef<HTMLDivElement>(null)

  // 焦点圈定 + Tab 循环 + Esc + body 滚动锁 + 卸载归还焦点（LoginModal.tsx:16-40 同款）
  useEffect(() => {
    if (!open || !user) return
    const prev = document.activeElement as HTMLElement | null
    panelRef.current?.querySelector<HTMLElement>(FOCUSABLE)?.focus()
    const overflow = document.body.style.overflow
    document.body.style.overflow = 'hidden'
    function onKey(e: KeyboardEvent) {
      if (e.key === 'Escape') { onClose(); return }
      if (e.key !== 'Tab' || !panelRef.current) return
      const nodes = Array.from(panelRef.current.querySelectorAll<HTMLElement>(FOCUSABLE))
      if (nodes.length === 0) return
      const first = nodes[0]
      const last = nodes[nodes.length - 1]
      if (e.shiftKey && document.activeElement === first) { e.preventDefault(); last.focus() }
      else if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first.focus() }
    }
    document.addEventListener('keydown', onKey)
    return () => {
      document.removeEventListener('keydown', onKey)
      document.body.style.overflow = overflow
      prev?.focus()
    }
  }, [open, user, onClose])

  if (!open) return null
  // 未登录（会话在挂载后失效）时退化为登录框，Esc/✕ 直接走 onClose 收口
  if (!user) return <LoginModal open onClose={onClose} />

  async function submit() {
    const text = body.trim()
    if (!text) { setError('请先填写反馈内容'); return }
    if (busy) return
    setBusy(true)
    setError(null)
    try {
      await api.submitFeedback({
        category,
        body: text,
        ...(contact.trim() ? { contact: contact.trim() } : {}),
      })
      setBody('')
      setContact('')
      onSubmitted?.()   // 成功 Toast 由 FeedbackEntry 持有（本组件 onClose 即卸载）
      onClose()
    } catch (e) {
      setError(e instanceof Error ? e.message : '提交失败，请稍后重试')
    } finally {
      setBusy(false)
    }
  }

  return (
    <>
      <div className="fb-mask" onClick={onClose}>
        <div
          className="fb-panel"
          role="dialog"
          aria-modal="true"
          aria-label="提交反馈"
          ref={panelRef}
          onClick={(e) => e.stopPropagation()}
        >
          <h2 className="fb-title">告诉我们哪里可以更好</h2>
          <p className="fb-tip">每条反馈都会有人读，并给你回复。</p>

          <div className="fb-field">
            <span className="fb-label" id="fb-category-label">类型</span>
            <div className="fb-pills" role="group" aria-labelledby="fb-category-label">
              {CATEGORIES.map((c) => (
                <button
                  key={c.value}
                  type="button"
                  className={`cat-pill${category === c.value ? ' is-active' : ''}`}
                  aria-pressed={category === c.value}
                  onClick={() => setCategory(c.value)}
                >
                  {c.label}
                </button>
              ))}
            </div>
          </div>

          <div className="fb-field">
            <label className="fb-label" htmlFor="fb-body">
              反馈内容
              <span className="fb-count" aria-live="polite">{body.length}/{BODY_MAX}</span>
            </label>
            <textarea
              id="fb-body"
              className="fb-textarea"
              rows={5}
              maxLength={BODY_MAX}
              value={body}
              onChange={(e) => setBody(e.target.value)}
              placeholder="发生了什么？期望是什么样？"
            />
          </div>

          <div className="fb-field">
            <label className="fb-label" htmlFor="fb-contact">
              联系方式<span className="fb-count" aria-live="polite">{contact.length}/{CONTACT_MAX}</span>
            </label>
            <input
              id="fb-contact"
              className="fb-input"
              maxLength={CONTACT_MAX}
              value={contact}
              onChange={(e) => setContact(e.target.value)}
              placeholder="选填，便于我们回复你"
            />
          </div>

          {error && <p className="fb-error" role="alert">{error}</p>}

          <div className="fb-actions">
            <Button variant="secondary" onClick={onClose}>取消</Button>
            <Button onClick={() => void submit()} loading={busy}>提交反馈</Button>
          </div>

          <button className="fb-close" aria-label="关闭反馈弹层" onClick={onClose}>✕</button>
        </div>
      </div>
    </>
  )
}

export default FeedbackModal
