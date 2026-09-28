// src/components/Toast.tsx —— 轻提示（spec 2026-09-28 §4.4）：单条、4s 自动消失，组件内自持计时
import { useEffect } from 'react'
import './Toast.css'

interface Props {
  message: string | null
  onDismiss: () => void
}

export default function Toast({ message, onDismiss }: Props) {
  useEffect(() => {
    if (!message) return
    const t = setTimeout(onDismiss, 4000)
    return () => clearTimeout(t)
  }, [message, onDismiss])
  if (!message) return null
  return <div className="toast" role="status">{message}</div>
}
