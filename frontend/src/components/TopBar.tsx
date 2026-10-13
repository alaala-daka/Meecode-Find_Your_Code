// src/components/TopBar.tsx —— 纸面墨线顶栏：logo（觅码 + 亮橙 Meecode，2026-08 新版圆头放大镜标志）+ 胶囊导航 + 线框搜索（未登录触达收藏/投稿/历史先弹登录）
import { useEffect, useState } from 'react'
import { Link, NavLink, useLocation, useNavigate, useSearchParams } from 'react-router-dom'
import { api } from '../api/client'
import type { ReplyNotification } from '../api/types'
import { useAuthStore } from '../store/authStore'
import { useNotificationStore } from '../store/notificationStore'
import { formatTime } from '../utils/format'
import Avatar from './Avatar'
import FeedbackEntry from './FeedbackEntry'
import LoginModal from './LoginModal'
import './CategoryBar.css'   // 复用 .cat-more-menu / .cat-more-item（铃铛下拉；跨组件复用类名显式引其定义文件）
import './SiteFooter.css'    // 复用 .footer-cta（铃铛底部「查看全部反馈」文字链）
import './TopBar.css'

export default function TopBar() {
  const [q, setQ] = useState('')
  const [loginOpen, setLoginOpen] = useState(false)
  const navigate = useNavigate()
  const [params] = useSearchParams()
  const location = useLocation()
  const user = useAuthStore((s) => s.user)
  const [menuOpen, setMenuOpen] = useState(false)
  const [notes, setNotes] = useState<ReplyNotification[]>([])
  const unread = useNotificationStore((s) => s.count)

  // 搜索结果页顶栏保留查询词；其余页不随 URL 回写
  useEffect(() => {
    if (location.pathname === '/search') setQ(params.get('q') ?? '')
  }, [location.pathname, params])

  function submitSearch() {
    const kw = q.trim()
    if (kw) navigate(`/search?q=${encodeURIComponent(kw)}`)
  }

  function goSubmit() {
    if (user) navigate('/submit')
    else setLoginOpen(true)
  }

  function goHistory() {
    if (user) navigate(`/user/${user.login}?tab=history`)
    else setLoginOpen(true)
  }

  // 「更多」式下拉：点外或 Esc 关闭（CategoryBar.tsx:21-35 同款）
  useEffect(() => {
    if (!menuOpen) return
    function onDoc(e: MouseEvent) {
      if (!(e.target as HTMLElement).closest('.bell-wrap')) setMenuOpen(false)
    }
    function onKey(e: KeyboardEvent) { if (e.key === 'Escape') setMenuOpen(false) }
    document.addEventListener('click', onDoc)
    document.addEventListener('keydown', onKey)
    return () => {
      document.removeEventListener('click', onDoc)
      document.removeEventListener('keydown', onKey)
    }
  }, [menuOpen])

  async function openBell() {
    if (!user) { setLoginOpen(true); return }   // UI 约束 §1.8：未登录点铃铛弹登录框（goHistory 同款）
    const next = !menuOpen
    setMenuOpen(next)
    if (!next) return
    try {
      const r = await api.replyNotifications(10)
      setNotes(r.items)
    } catch {
      setNotes([])
    }
  }

  return (
    <header className="topbar">
      <div className="topbar-inner">
        <div className="topbar-left">
          <Link className="logo" to="/" aria-label="觅码 首页">
            <span className="logo-mark" aria-hidden="true">
              <svg viewBox="0 0 32 32" width="26" height="26">
                <circle cx="13.5" cy="13.5" r="9.75" fill="none" stroke="currentColor" strokeWidth="3.1" />
                <line x1="21.7" y1="21.7" x2="28.3" y2="28.3" stroke="currentColor" strokeWidth="3.1" strokeLinecap="round" />
                <circle cx="12.3" cy="14" r="1.75" fill="currentColor" />
                <line x1="16.7" y1="11.6" x2="16.7" y2="15.8" stroke="currentColor" strokeWidth="2.3" strokeLinecap="round" />
              </svg>
            </span>
            <span className="logo-text">
              觅码<span className="logo-sub">Meecode</span>
            </span>
          </Link>
          <nav className="topbar-nav">
            <NavLink
              className={({ isActive }) => `nav-item${isActive ? ' is-current' : ''}`}
              to="/"
              end
            >首页</NavLink>
          </nav>
        </div>
        <div className="topbar-search">
          <svg className="search-glass" viewBox="0 0 16 16" width="15" height="15" aria-hidden="true">
            <circle cx="7" cy="7" r="5" fill="none" stroke="currentColor" strokeWidth="1.8" />
            <line x1="11" y1="11" x2="14" y2="14" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" />
          </svg>
          <input
            className="search-input"
            name="q"
            autoComplete="off"
            spellCheck={false}
            value={q}
            onChange={(e) => setQ(e.target.value)}
            onKeyDown={(e) => e.key === 'Enter' && submitSearch()}
            placeholder="搜索仓库、标签、一句话卖点…"
            aria-label="搜索"
          />
          <button className="search-btn" onClick={submitSearch} aria-label="搜索按钮">搜索</button>
        </div>
        <div className="topbar-right">
          <button className="icon-btn" aria-label="浏览历史" onClick={goHistory}>
            <svg viewBox="0 0 20 20" width="18" height="18" aria-hidden="true">
              <circle cx="10" cy="10" r="7.5" fill="none" stroke="currentColor" strokeWidth="1.6" />
              <polyline points="10,5.5 10,10 13.5,12" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" />
            </svg>
          </button>
          <div className="bell-wrap">
            <button
              type="button"
              className="icon-btn"
              aria-label="反馈回复通知"
              aria-expanded={menuOpen}
              aria-haspopup="menu"
              onClick={() => void openBell()}
            >
              <svg viewBox="0 0 20 20" width="18" height="18" aria-hidden="true">
                <path
                  d="M10 3a4.5 4.5 0 0 1 4.5 4.5V11l1.5 2.5H4L5.5 11V7.5A4.5 4.5 0 0 1 10 3z"
                  fill="none" stroke="currentColor" strokeWidth={1.6} strokeLinejoin="round"
                />
                <path d="M8 16a2 2 0 0 0 4 0" fill="none" stroke="currentColor"
                  strokeWidth={1.6} strokeLinecap="round" />
              </svg>
              {unread > 0 && <span className="bell-dot" aria-label={`${unread} 条未读回复`} />}
            </button>
            {menuOpen && (
              <div className="cat-more-menu bell-menu" role="menu">
                {notes.length === 0 && <p className="bell-empty">暂无回复</p>}
                {notes.map((n) => (
                  <Link
                    key={n.reply_id}
                    to={`/my/feedback/${n.feedback_id}`}
                    className="cat-more-item"
                    role="menuitem"
                    onClick={() => setMenuOpen(false)}
                  >
                    <span className="bell-note-preview">{n.reply_body_preview}</span>
                    <span className="bell-note-time">{formatTime(new Date(n.created_at * 1000).toISOString())}</span>
                  </Link>
                ))}
                <Link
                  to="/my/feedback"
                  className="footer-cta bell-all"   // 底部文字链沿 .footer-cta（UI 约束 §1.13）
                  onClick={() => setMenuOpen(false)}
                >
                  查看全部反馈 →
                </Link>
              </div>
            )}
          </div>
          <FeedbackEntry variant="icon" />
          <button className="btn btn-primary btn-submit" onClick={goSubmit}>+ 推广我的仓库</button>
          {user ? (
            <Link className="avatar-link" to={`/user/${user.login}`} aria-label="个人主页">
              <Avatar login={user.login} avatarUrl={user.avatar_url} className="avatar-sm" />
            </Link>
          ) : (
            <button className="login-entry" onClick={() => setLoginOpen(true)}>登录</button>
          )}
        </div>
      </div>
      <LoginModal open={loginOpen} onClose={() => setLoginOpen(false)} />
    </header>
  )
}
