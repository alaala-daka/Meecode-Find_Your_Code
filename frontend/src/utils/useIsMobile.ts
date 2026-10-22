// src/utils/useIsMobile.ts —— 视口断点判定（与 TopBar.css 移动断点 720px 保持一致）；jsdom/无 matchMedia 环境按桌面处理
import { useEffect, useState } from 'react'

export function useIsMobile(maxWidth = 720) {
  const query = `(max-width: ${maxWidth}px)`
  const [isMobile, setIsMobile] = useState(() =>
    typeof window.matchMedia === 'function' ? window.matchMedia(query).matches : false
  )

  useEffect(() => {
    if (typeof window.matchMedia !== 'function') return
    const mql = window.matchMedia(query)
    const onChange = () => setIsMobile(mql.matches)
    onChange()
    // Safari <14 仅支持旧式 addListener（ProfilePage.tsx:32 同款防御风格）
    if (mql.addEventListener) mql.addEventListener('change', onChange)
    else mql.addListener(onChange)
    return () => {
      if (mql.removeEventListener) mql.removeEventListener('change', onChange)
      else mql.removeListener(onChange)
    }
  }, [query])

  return isMobile
}
