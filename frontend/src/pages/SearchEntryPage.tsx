// src/pages/SearchEntryPage.tsx —— 搜索中间页：全宽输入 + 自动聚焦（手机端顶栏空间不足看不清键入字，点击搜索入口跳至此处输入），提交进 /search 结果页
import { useState } from 'react'
import { useLocation, useNavigate } from 'react-router-dom'
import TopBar from '../components/TopBar'
import './SearchEntryPage.css'

export default function SearchEntryPage() {
  const [q, setQ] = useState('')
  const navigate = useNavigate()
  const location = useLocation()

  function submit() {
    const kw = q.trim()
    if (kw) navigate(`/search?q=${encodeURIComponent(kw)}`)
  }

  function cancel() {
    // 站内跳入回上一页；直达本页（无历史栈）回首页，避免「取消」无响应
    if (location.key === 'default') navigate('/')
    else navigate(-1)
  }

  return (
    <>
      <TopBar />
      <main id="main" className="page-shell search-entry-page">
        <div className="entry-bar">
          <div className="entry-field">
            <svg className="entry-glass" viewBox="0 0 16 16" width="16" height="16" aria-hidden="true">
              <circle cx="7" cy="7" r="5" fill="none" stroke="currentColor" strokeWidth="1.8" />
              <line x1="11" y1="11" x2="14" y2="14" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" />
            </svg>
            <input
              className="entry-input"
              value={q}
              onChange={(e) => setQ(e.target.value)}
              onKeyDown={(e) => e.key === 'Enter' && submit()}
              placeholder="搜索仓库、标签、一句话卖点…"
              aria-label="搜索"
              autoComplete="off"
              spellCheck={false}
              enterKeyHint="search"
              autoFocus // 用户点击搜索入口跳转而来，聚焦即可唤起键盘
            />
            {q && (
              <button className="entry-clear" onClick={() => setQ('')} aria-label="清空">×</button>
            )}
          </div>
          <button className="entry-submit" onClick={submit}>搜索</button>
          <button className="entry-cancel" onClick={cancel}>取消</button>
        </div>
        <p className="entry-hint">支持仓库名、标签与一句话卖点；回车或点「搜索」出结果</p>
      </main>
    </>
  )
}
