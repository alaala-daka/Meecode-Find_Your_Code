// src/components/CategoryBar.tsx —— 规范 §6.3：胶囊式 tab，吸顶
import { useEffect, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { api } from '../api/client'
import { useFeedStore } from '../store/feedStore'
import './CategoryBar.css'

const VISIBLE_COUNT = 8

export default function CategoryBar() {
  const [cats, setCats] = useState<string[]>([])
  const [moreOpen, setMoreOpen] = useState(false)
  const [params, setParams] = useSearchParams()
  const active = params.get('cat')

  useEffect(() => {
    api.categories().then(setCats).catch(() => setCats([]))
  }, [])

  // 「更多」下拉：Esc 或点击外部关闭
  useEffect(() => {
    if (!moreOpen) return
    function onDoc(e: MouseEvent) {
      if (!(e.target as HTMLElement).closest('.cat-more-wrap')) setMoreOpen(false)
    }
    function onKey(e: KeyboardEvent) {
      if (e.key === 'Escape') setMoreOpen(false)
    }
    document.addEventListener('click', onDoc)
    document.addEventListener('keydown', onKey)
    return () => {
      document.removeEventListener('click', onDoc)
      document.removeEventListener('keydown', onKey)
    }
  }, [moreOpen])

  function pick(cat: string | null) {
    if (cat) params.set('cat', cat)
    else params.delete('cat')
    setParams(params, { replace: true })
    void useFeedStore.getState().load(cat)
    setMoreOpen(false)
  }

  const visible = cats.slice(0, VISIBLE_COUNT)
  const overflow = cats.slice(VISIBLE_COUNT)

  return (
    <div className="category-bar">
      <div className="category-inner">
        <button className={`cat-pill ${!active ? 'is-active' : ''}`} onClick={() => pick(null)}>全部</button>
        {visible.map((c) => (
          <button key={c} className={`cat-pill ${active === c ? 'is-active' : ''}`} onClick={() => pick(c)}>
            {c}
          </button>
        ))}
        {overflow.length > 0 && (
          <div className="cat-more-wrap">
            <button className="cat-pill" aria-expanded={moreOpen} aria-haspopup="menu"
              onClick={() => setMoreOpen((v) => !v)}>更多 ▾</button>
            {moreOpen && (
              <div className="cat-more-menu" role="menu">
                {overflow.map((c) => (
                  <button key={c} className={`cat-more-item ${active === c ? 'is-active' : ''}`} role="menuitem" onClick={() => pick(c)}>
                    {c}
                  </button>
                ))}
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  )
}
