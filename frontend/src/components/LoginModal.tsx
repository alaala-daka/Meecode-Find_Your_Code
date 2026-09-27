// src/components/LoginModal.tsx —— 规范 §8.3 + 可达性：焦点圈定/Esc/关闭按钮/滚动锁
import { useEffect, useRef } from 'react'
import { useAuthStore } from '../store/authStore'
import Button from './Button'
import './LoginModal.css'

interface Props {
  open: boolean
  onClose: () => void
}

export default function LoginModal({ open, onClose }: Props) {
  const login = useAuthStore((s) => s.login)
  const modalRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (!open) return
    const prev = document.activeElement as HTMLElement | null
    const first = modalRef.current?.querySelector<HTMLElement>('button')
    first?.focus()
    const prevOverflow = document.body.style.overflow
    document.body.style.overflow = 'hidden'
    function onKey(e: KeyboardEvent) {
      if (e.key === 'Escape') { onClose(); return }
      if (e.key === 'Tab' && modalRef.current) {
        const focusables = modalRef.current.querySelectorAll<HTMLElement>('button')
        if (focusables.length === 0) return
        const firstF = focusables[0]
        const lastF = focusables[focusables.length - 1]
        if (e.shiftKey && document.activeElement === firstF) { e.preventDefault(); lastF.focus() }
        else if (!e.shiftKey && document.activeElement === lastF) { e.preventDefault(); firstF.focus() }
      }
    }
    document.addEventListener('keydown', onKey)
    return () => {
      document.removeEventListener('keydown', onKey)
      document.body.style.overflow = prevOverflow
      prev?.focus()
    }
  }, [open, onClose])

  if (!open) return null
  return (
    <div className="login-mask" onClick={onClose}>
      <div
        className="login-modal"
        role="dialog"
        aria-modal="true"
        aria-label="登录"
        aria-describedby="login-tip"
        ref={modalRef}
        onClick={(e) => e.stopPropagation()}
      >
        <span className="login-logo" aria-hidden="true">
          <svg viewBox="0 0 32 32" width="34" height="34">
            <circle cx="13.5" cy="13.5" r="9.75" fill="none" stroke="currentColor" strokeWidth="3.1" />
            <line x1="21.7" y1="21.7" x2="28.3" y2="28.3" stroke="currentColor" strokeWidth="3.1" strokeLinecap="round" />
            <circle cx="12.3" cy="14" r="1.75" fill="currentColor" />
            <line x1="16.7" y1="11.6" x2="16.7" y2="15.8" stroke="currentColor" strokeWidth="2.3" strokeLinecap="round" />
          </svg>
        </span>
        <p className="login-brand">觅码<span className="login-brand-sub">Meecode</span></p>
        <p className="login-tip" id="login-tip">登录后即可收藏、点赞与推广仓库</p>
        <p className="login-scope">登录将获得 GitHub public_repo 权限，仅用于为你点星/取消星</p>
        <Button onClick={() => { login(); onClose() }}>用 GitHub 登录</Button>
        <button className="login-close" aria-label="关闭登录弹层" onClick={onClose}>✕</button>
      </div>
    </div>
  )
}
