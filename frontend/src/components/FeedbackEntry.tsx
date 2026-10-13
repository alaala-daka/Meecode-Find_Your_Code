// src/components/FeedbackEntry.tsx —— 反馈入口（顶栏图标 / 页脚文字链共用；自带登录守卫、弹窗开合与成功 Toast）
import { useCallback, useState } from 'react'

import { useAuthStore } from '../store/authStore'
import FeedbackModal from './FeedbackModal'
import LoginModal from './LoginModal'
import Toast from './Toast'
import './SiteFooter.css'   // 复用 .footer-cta（text 变体；SubmitPage.tsx:12 先例）
import './TopBar.css'       // 复用 .icon-btn（icon 变体）

export function FeedbackEntry({ variant }: { variant: 'icon' | 'text' }) {
  const user = useAuthStore((s) => s.user)
  const [open, setOpen] = useState(false)
  const [loginOpen, setLoginOpen] = useState(false)
  const [toast, setToast] = useState<string | null>(null)

  // FeedbackModal/LoginModal 的焦点 effect 依赖 onClose，内联箭头会每次渲染重置焦点圈定；
  // 稳定化 handler（Task 10 审查前向修正，已获授权）
  const closeLogin = useCallback(() => setLoginOpen(false), [])
  const closeFeedback = useCallback(() => setOpen(false), [])
  const onSubmitted = useCallback(() => setToast('反馈已提交，感谢你的建议'), [])
  const dismissToast = useCallback(() => setToast(null), [])

  function openFeedback() {
    if (!user) { setLoginOpen(true); return }
    setOpen(true)
  }

  if (variant === 'text') {
    return (
      <>
        <button type="button" className="footer-cta" onClick={openFeedback}>反馈</button>
        <LoginModal open={loginOpen} onClose={closeLogin} />
        <FeedbackModal open={open} onClose={closeFeedback} onSubmitted={onSubmitted} />
        <Toast message={toast} onDismiss={dismissToast} />
      </>
    )
  }

  return (
    <>
      <button type="button" className="icon-btn" aria-label="反馈" onClick={openFeedback}>
        <svg viewBox="0 0 20 20" width="18" height="18" aria-hidden="true">
          <path
            d="M3.5 5.5a1.5 1.5 0 0 1 1.5-1.5h10a1.5 1.5 0 0 1 1.5 1.5v6a1.5 1.5 0 0 1-1.5 1.5H8l-3 3.2v-3.2H5a1.5 1.5 0 0 1-1.5-1.5z"
            fill="none"
            stroke="currentColor"
            strokeWidth={1.6}
            strokeLinejoin="round"
          />
        </svg>
      </button>
      <LoginModal open={loginOpen} onClose={closeLogin} />
      <FeedbackModal open={open} onClose={closeFeedback} onSubmitted={onSubmitted} />
      <Toast message={toast} onDismiss={dismissToast} />
    </>
  )
}

export default FeedbackEntry
