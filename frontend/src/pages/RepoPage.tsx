// src/pages/RepoPage.tsx —— 规范 §7.3
import { useEffect, useRef, useState } from 'react'
import { useNavigate, useParams, useSearchParams } from 'react-router-dom'
import { api } from '../api/client'
import type { RepoDetail, RepoFile, RepoTreeItem } from '../api/types'
import Capsule from '../components/Capsule'
import CodeView from '../components/CodeView'
import EmptyState from '../components/EmptyState'
import FileTree from '../components/FileTree'
import IconAction from '../components/IconAction'
import LoginModal from '../components/LoginModal'
import ReadmeSection from '../components/ReadmeSection'
import RepoRail from '../components/RepoRail'
import Tabs from '../components/Tabs'
import TopBar from '../components/TopBar'
import { useAuthStore } from '../store/authStore'
import { capsuleBg, capsuleText, languageColor } from '../theme/languageColors'
import { formatCount, formatTime } from '../utils/format'
// 显式导入所复用样式（.source-badge）的定义文件，避免依赖打包顺序
import '../components/RepoCard.css'
import ExplainPanel from '../explain/ExplainPanel'
import './RepoPage.css'

const TAB_ITEMS = [
  { key: 'files', label: '文件预览' },
  { key: 'explain', label: '仓库解读' },
]

export default function RepoPage() {
  const { id } = useParams()
  const repoId = Number(id)
  const navigate = useNavigate()
  const [params, setParams] = useSearchParams()
  const tab = params.get('tab') === 'explain' ? 'explain' : 'files'
  const fileParam = params.get('file')
  const user = useAuthStore((s) => s.user)
  const [detail, setDetail] = useState<RepoDetail | null>(null)
  const [loadError, setLoadError] = useState(false)
  const [tree, setTree] = useState<RepoTreeItem[]>([])
  const [treeError, setTreeError] = useState(false)
  const [file, setFile] = useState<RepoFile | null>(null)
  const [fileError, setFileError] = useState(false)
  const [liked, setLiked] = useState(false)
  const [faved, setFaved] = useState(false)
  const [busy, setBusy] = useState<'like' | 'fav' | null>(null)
  const [actionError, setActionError] = useState<string | null>(null)
  const [loginOpen, setLoginOpen] = useState(false)
  const fileReqRef = useRef(0) // 文件请求令牌：丢弃过期响应，防切仓库/快速点文件时旧响应覆盖

  useEffect(() => {
    let alive = true
    api.repo(repoId)
      .then((d) => {
        if (!alive) return
        setDetail(d)
        setLiked(d.liked)
        setFaved(d.favorited)
      })
      .catch(() => { if (alive) setLoadError(true) })
    api.repoTree(repoId).then((t) => {
      if (!alive) return
      setTree(t)
      if (fileParam) return // URL 指定文件，交给下方 param effect 加载
      const first = t.find((n) => n.type === 'file')
      if (first) void selectFile(first.path)
    }).catch(() => { if (alive) setTreeError(true) })
    return () => { alive = false }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [repoId])

  // URL 文件深链：?file=src/main.py 直接加载指定文件
  useEffect(() => {
    if (tab === 'files' && fileParam) void selectFile(fileParam)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [fileParam, tab, repoId])

  function switchTab(k: string) {
    const p = new URLSearchParams(params)
    p.set('tab', k)
    setParams(p)
  }

  function onSelectFile(p: string) {
    const n = new URLSearchParams(params)
    n.set('file', p)
    setParams(n, { replace: true })
  }

  async function selectFile(path: string) {
    const req = ++fileReqRef.current
    setFileError(false)
    try {
      const f = await api.repoFile(repoId, path)
      if (req !== fileReqRef.current) return // 已有更新的请求，丢弃过期响应
      setFile(f)
    } catch {
      if (req !== fileReqRef.current) return
      setFileError(true)
      setFile(null)
    }
  }

  function gate(fn: () => void) {
    if (user) fn()
    else setLoginOpen(true)
  }

  async function toggleLike() {
    if (busy) return
    const next = !liked
    setBusy('like')
    setActionError(null)
    setLiked(next)
    try {
      await api.interact(repoId, 'like', next)
      setDetail((d) => d ? { ...d, likes: d.likes + (next ? 1 : -1) } : d)
    } catch {
      setLiked(!next) // 回滚乐观更新
      setActionError('操作失败，请重试')
    } finally {
      setBusy(null)
    }
  }

  async function toggleFav() {
    if (busy) return
    const next = !faved
    setBusy('fav')
    setActionError(null)
    setFaved(next)
    try {
      await api.interact(repoId, 'favorite', next)
      setDetail((d) => (d && d.favorites_count != null ? { ...d, favorites_count: d.favorites_count + (next ? 1 : -1) } : d))
    } catch {
      setFaved(!next) // 回滚乐观更新
      setActionError('操作失败，请重试')
    } finally {
      setBusy(null)
    }
  }

  if (loadError) {
    return (
      <>
        <TopBar />
        <main id="main" className="page-shell">
          <EmptyState title="仓库不存在或已下架" actionLabel="回首页" onAction={() => navigate('/')} />
        </main>
      </>
    )
  }

  if (!detail) {
    return (<><TopBar /><main id="main" className="page-shell"><p className="repo-loading">加载中…</p></main></>)
  }

  return (
    <>
      <TopBar />
      <main id="main" className="page-shell repo-page">
        <div className="repo-page-grid">
          <div className="repo-main">
            <section className="repo-head">
              <h1 className="repo-name">{detail.title}</h1>
              <p className="repo-tagline">{detail.tagline_zh}</p>
              <p className="repo-meta">
                <span className="repo-stars">★ {formatCount(detail.stars)}</span>
                {detail.language && (
                  <span className="repo-lang">
                    <span className="lang-dot" style={{ backgroundColor: languageColor(detail.language) }} aria-hidden="true" />
                    {detail.language}
                  </span>
                )}
                <span>浏览 {formatCount(detail.views)}</span>
                <span>{formatTime(detail.published_at)}发布</span>
                <span className={`source-badge badge-${detail.source}`}>
                  {detail.source === 'submitted' ? '投稿' : '采集'}
                </span>
                <span className="repo-meta-actions">
                  <IconAction kind="like" on={liked} count={detail.likes} busy={busy === 'like'}
                    onClick={() => gate(() => void toggleLike())} />
                  <IconAction kind="favorite" on={faved} count={detail.favorites_count} busy={busy === 'fav'}
                    onClick={() => gate(() => void toggleFav())} />
                </span>
              </p>
              {detail.topics.length > 0 && (
                <p className="repo-topics">
                  {detail.topics.map((t) => (
                    <Capsule key={t} label={t}
                      bg={capsuleBg(languageColor(detail.language))}
                      fg={capsuleText(languageColor(detail.language))} />
                  ))}
                </p>
              )}
              {actionError && <p className="action-error" role="alert">{actionError}</p>}
            </section>

            <Tabs items={TAB_ITEMS} active={tab} onChange={switchTab} panelId="repo-tab-panel" />

            <div className="repo-tab-body" key={tab} id="repo-tab-panel" role="tabpanel" aria-label={tab === 'files' ? '文件预览' : '仓库解读'}>
              {tab === 'files' && (
                <div className="repo-files">
                  <FileTree tree={tree} current={file?.path ?? null} onSelect={(p) => onSelectFile(p)} />
                  {treeError && (
                    <p className="file-fallback">
                      文件树加载失败，<a href={detail.github_url} target="_blank" rel="noreferrer">去 GitHub 查看 ↗</a>
                    </p>
                  )}
                  {!treeError && file && <CodeView file={file} githubUrl={detail.github_url} defaultBranch={detail.default_branch} />}
                  {!treeError && fileError && (
                    <p className="file-fallback">
                      文件预览失败，<a href={detail.github_url} target="_blank" rel="noreferrer">去 GitHub 查看 ↗</a>
                    </p>
                  )}
                </div>
              )}
              {tab === 'explain' && <ExplainPanel repo={detail} />}
            </div>

            <ReadmeSection repoId={repoId} tree={tree} fullName={detail.full_name} defaultBranch={detail.default_branch} />

            <section className="repo-discussions">
              <h2 className="discussions-title">讨论</h2>
              <p className="discussions-body">评论区开发中</p>
            </section>
          </div>

          <RepoRail repo={detail} />
        </div>

        <LoginModal open={loginOpen} onClose={() => setLoginOpen(false)} />
      </main>
    </>
  )
}
