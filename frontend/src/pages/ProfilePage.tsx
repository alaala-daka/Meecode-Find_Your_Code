// src/pages/ProfilePage.tsx —— 规范 §7.5
import { useCallback, useEffect, useState } from 'react'
import { useNavigate, useParams, useSearchParams } from 'react-router-dom'
import { api } from '../api/client'
import type { RepoCardData, UserProfile } from '../api/types'
import Avatar from '../components/Avatar'
import EmptyState from '../components/EmptyState'
import ErrorBanner from '../components/ErrorBanner'
import RepoCard from '../components/RepoCard'
import Tabs from '../components/Tabs'
import TopBar from '../components/TopBar'
import { useAuthStore } from '../store/authStore'
import './ProfilePage.css'

const TAB_ITEMS = [
  { key: 'repos', label: '我的仓库' },
  { key: 'favs', label: '收藏夹' },
  { key: 'history', label: '浏览历史' },
]

export default function ProfilePage() {
  const { login = '' } = useParams()
  const navigate = useNavigate()
  const me = useAuthStore((s) => s.user)
  const isMe = me?.login === login
  const [params, setParams] = useSearchParams()
  const tab = params.get('tab') ?? 'repos'
  const [profile, setProfile] = useState<UserProfile | null>(null)
  const [editingBio, setEditingBio] = useState(false)
  const [lists, setLists] = useState<Record<'repos' | 'favs' | 'history', RepoCardData[]>>({ repos: [], favs: [], history: [] })
  const [loadError, setLoadError] = useState(false)
  const finePointer = typeof window.matchMedia === 'function'
    ? window.matchMedia('(pointer: fine)').matches
    : true

  const loadAll = useCallback(async () => {
    setLoadError(false)
    try {
      const [p, repos, favs, history] = await Promise.all([
        api.userProfile(login),
        api.userRepos(login),
        api.userFavorites(login),
        api.userHistory(login),
      ])
      setProfile(p)
      setLists({ repos, favs, history })
    } catch {
      setLoadError(true) // 规范 §8.2：轻量错误条 + 重试，不卡死「加载中」
    }
  }, [login])

  useEffect(() => { void loadAll() }, [loadAll])

  function switchTab(key: string) {
    params.set('tab', key)
    setParams(params, { replace: true })
  }

  async function saveBio(value: string) {
    setEditingBio(false)
    if (!profile || value === profile.bio) return
    setProfile({ ...profile, bio: value })
    await api.setBio(value)
  }

  async function delist(repo: RepoCardData) {
    if (!window.confirm(`确定下架「${repo.title}」吗？`)) return
    await api.delist(repo.id)
    void loadAll()
  }

  if (!profile && !loadError) {
    return (<><TopBar /><main id="main" className="page-shell"><p className="profile-loading">加载中…</p></main></>)
  }

  if (!profile) {
    // 初次加载失败：profile 尚为 null，不能落入主渲染（profile.login 会崩），独立错误分支兜底
    return (<><TopBar /><main id="main" className="page-shell"><ErrorBanner message="主页加载失败" onRetry={() => void loadAll()} /></main></>)
  }

  const current = lists[tab as 'repos' | 'favs' | 'history'] ?? []
  const emptyText = tab === 'repos' ? '你还没有推广过仓库'
    : tab === 'favs' ? '还没有收藏' : '还没有浏览记录'

  return (
    <>
      <TopBar />
      <div className="profile-banner">
        <header className="page-shell profile-head-wrap">
          <Avatar login={profile.login} avatarUrl={profile.avatar_url} className="profile-avatar" variant="square" />
          <div className="profile-info">
            <h1 className="profile-name">{profile.login}</h1>
            {editingBio ? (
              <input
                className="bio-input"
                defaultValue={profile.bio}
                autoFocus={finePointer} // 仅桌面指针设备自动聚焦，避免移动端弹键盘
                onBlur={(e) => void saveBio(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === 'Enter') void saveBio((e.target as HTMLInputElement).value)
                  if (e.key === 'Escape') setEditingBio(false)
                }}
                aria-label="签名"
              />
            ) : (
              <p className="profile-bio">
                {profile.bio || '这个人很懒，还没有写签名'}
                {isMe && (
                  <button className="bio-edit" aria-label="编辑签名" onClick={() => setEditingBio(true)}>✎</button>
                )}
              </p>
            )}
            <p className="profile-stats">
              <span>仓库 <b>{profile.repo_count}</b></span>
              <span>获赞星 <b>{profile.star_count}</b></span>
              <span>被收藏 <b>{profile.favorite_count}</b></span>
            </p>
          </div>
        </header>
      </div>
      <main id="main" className="page-shell profile-page">
        {loadError && <ErrorBanner message="主页加载失败" onRetry={() => void loadAll()} />}
        <Tabs
          items={TAB_ITEMS.map((t) => ({ ...t, count: lists[t.key as 'repos' | 'favs' | 'history'].length }))}
          active={tab}
          onChange={switchTab}
          panelId="profile-tab-panel"
        />

        <div className="profile-tab-body" key={tab} id="profile-tab-panel" role="tabpanel" aria-label={tab === 'repos' ? '我的仓库' : tab === 'favs' ? '收藏夹' : '浏览历史'}>
          {current.length === 0 ? (
            <EmptyState title={emptyText}
              actionLabel={tab === 'repos' ? '推广我的仓库' : '去首页逛逛'}
              onAction={() => navigate(tab === 'repos' ? '/submit' : '/')} />
          ) : (
            <div className="repo-grid">
              {current.map((c) => (
                <div className="profile-card-wrap" key={c.id}>
                  <RepoCard data={c} />
                  {isMe && tab === 'repos' && (
                    <button className="delist-btn" onClick={() => void delist(c)}>下架</button>
                  )}
                </div>
              ))}
            </div>
          )}
        </div>
      </main>
    </>
  )
}
