// src/components/StarSyncModal.tsx —— 撤星确认弹窗（spec 2026-09-28 §4.4）：双按钮选择
import { useEffect, useRef } from 'react'
import Button from './Button'
import './StarSyncModal.css'

interface Props {
  open: boolean
  onConfirmAuth: () => void   // 授权并同步取消
  onLocalOnly: () => void     // 仅取消本地收藏
  onClose: () => void
}

export default function StarSyncModal({ open, onConfirmAuth, onLocalOnly, onClose }: Props) {
  const modalRef = useRef<HTMLDivElement>(null)
  useEffect(() => {
    if (!open) return
    const prev = document.activeElement as HTMLElement | null
    modalRef.current?.querySelector<HTMLElement>('button')?.focus()
    const prevOverflow = document.body.style.overflow
    document.body.style.overflow = 'hidden'
    function onKey(e: KeyboardEvent) {
      if (e.key === 'Escape') { onClose(); return }
      if (e.key === 'Tab' && modalRef.current) {
        const focusables = modalRef.current.querySelectorAll<HTMLElement>('button')
        if (focusables.length === 0) return
        const first = focusables[0]; const last = focusables[focusables.length - 1]
        if (e.shiftKey && document.activeElement === first) { e.preventDefault(); last.focus() }
        else if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first.focus() }
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
    <div className="star-modal-mask" onClick={onClose}>
      <div className="star-modal" role="dialog" aria-modal="true"
           aria-label="取消收藏将同步取消 GitHub 星" ref={modalRef}
           onClick={(e) => e.stopPropagation()}>
        <p className="star-modal-title">取消收藏将同步取消 GitHub 星</p>
        <p className="star-modal-tip">该仓库的 GitHub 星（含你手动点的）将一并取消。选择仅本地则保留 GitHub 星。</p>
        <Button onClick={onConfirmAuth}>授权并同步取消</Button>
        <button className="star-modal-local" onClick={onLocalOnly}>仅取消本地收藏</button>
        <button className="star-modal-close" aria-label="关闭" onClick={onClose}>✕</button>
      </div>
    </div>
  )
}
