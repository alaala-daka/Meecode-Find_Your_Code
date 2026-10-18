// src/pages/SubmitPage.tsx —— 三步投稿向导（选仓库 → 编辑推广页 → 发布）；卡片预览即真实 RepoCard
import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { api } from '../api/client'
import type { MyGithubRepo, RepoCardData } from '../api/types'
import Button from '../components/Button'
import LoginModal from '../components/LoginModal'
import RepoCard from '../components/RepoCard'
import TopBar from '../components/TopBar'
import { useAuthStore } from '../store/authStore'
// 显式导入所复用样式的定义文件（.cat-pill/.source-badge），避免依赖打包顺序、兼容未来路由级代码分割
import '../components/CategoryBar.css'
import '../components/RepoCard.css'
import './SubmitPage.css'

const STEPS = ['选仓库', '编辑推广页', '发布']
const TAGLINE_MAX = 40

export default function SubmitPage() {
  const navigate = useNavigate()
  const user = useAuthStore((s) => s.user)
  const [step, setStep] = useState(0)
  const [repos, setRepos] = useState<MyGithubRepo[]>([])
  const [picked, setPicked] = useState<MyGithubRepo | null>(null)
  const [cats, setCats] = useState<string[]>([])
  const [tagline, setTagline] = useState('')
  const [intro, setIntro] = useState('')
  const [category, setCategory] = useState('')
  const [drafting, setDrafting] = useState(false)
  const [publishing, setPublishing] = useState(false)
  const [actionError, setActionError] = useState<string | null>(null)
  const [loginOpen, setLoginOpen] = useState(false)
  const [aiSuggested, setAiSuggested] = useState('')
  const [customTag, setCustomTag] = useState('')
  const [customOpen, setCustomOpen] = useState(false)

  useEffect(() => {
    if (!user) return
    // 真实客户端请求失败会 reject:捕获并经既有 actionError 提示,避免未处理拒绝
    void api.myRepos().then(setRepos)
      .catch(() => setActionError('我的仓库加载失败'))
    void api.categories().then((cs) => { setCats(cs); setCategory(cs[0]) })
      .catch(() => setActionError('分类加载失败'))
  }, [user])

  // 未保存变更离开提醒（编辑推广页有内容时）
  useEffect(() => {
    if (step !== 1) return
    const dirty = tagline.trim().length > 0 || intro.trim().length > 0
    if (!dirty) return
    const onBeforeUnload = (e: BeforeUnloadEvent) => { e.preventDefault(); e.returnValue = '' }
    window.addEventListener('beforeunload', onBeforeUnload)
    return () => window.removeEventListener('beforeunload', onBeforeUnload)
  }, [step, tagline, intro])

  async function aiDraft() {
    if (!picked) return
    setDrafting(true)
    setActionError(null)
    try {
      const draft = await api.aiDraft(picked.github_id)
      setTagline(draft.tagline_zh.slice(0, TAGLINE_MAX))
      setIntro(draft.intro_zh)
      // 自动推荐分类：选中 AI 建议并打上角标，用户可随时改选
      setCategory(draft.suggested_category)
      setAiSuggested(draft.suggested_category)
      setCustomOpen(false)
    } catch {
      setActionError('AI 生成失败，可先手写，稍后再试')
    } finally {
      setDrafting(false)
    }
  }

  async function publish() {
    if (!picked || !tagline.trim()) return
    setPublishing(true)
    setActionError(null)
    try {
      await api.submitRepo({
        full_name: picked.full_name,
        tagline_zh: tagline.trim(),
        intro_zh: intro,
        category,
        cover_url: null,
      })
      setStep(2)
    } catch {
      setActionError('发布失败，请重试')
    } finally {
      setPublishing(false)
    }
  }

  if (!user) {
    return (
      <>
        <TopBar />
        <main id="main" className="page-shell submit-page">
          <div className="submit-login-guard">
            <p className="guard-title">用 GitHub 登录后即可推广你的仓库</p>
            <Button onClick={() => setLoginOpen(true)}>用 GitHub 登录</Button>
          </div>
          <LoginModal open={loginOpen} onClose={() => setLoginOpen(false)} />
        </main>
      </>
    )
  }

  // 预览卡片：把选中的 GitHub 仓库映射成真实 RepoCard 形状（id/互动计数为占位值，仅用于预览）
  const previewCard: RepoCardData | null = picked
    ? {
        id: 0, full_name: picked.full_name, title: picked.title, owner_login: user.login,
        language: picked.language, topics: [], stars: picked.stars, views: 0, likes: 0,
        source: 'submitted', category, tagline_zh: tagline || '一句话卖点会显示在这里',
        published_at: new Date().toISOString(), cover_url: null,
      }
    : null

  return (
    <>
      <TopBar />
      <main id="main" className="page-shell submit-page">
        <ol className="steps">
          {STEPS.map((s, i) => (
            <li key={s} className={`step ${i === step ? 'is-current' : ''} ${i < step ? 'is-done' : ''}`}>
              <span className="step-dot" aria-hidden="true">{i < step ? '✓' : i + 1}</span>
              {s}
            </li>
          ))}
        </ol>

        {step === 0 && (
          <section className="submit-section">
            <ul className="my-repos">
              {repos.map((r) => (
                <li key={r.github_id}>
                  <label className={`my-repo ${picked?.github_id === r.github_id ? 'is-picked' : ''}`}>
                    <input type="radio" name="pick" checked={picked?.github_id === r.github_id}
                      onChange={() => setPicked(r)} aria-label={r.title} />
                    <span className="my-repo-name">{r.title}</span>
                    <span className="my-repo-stars">★ {r.stars}</span>
                    {r.status === 'published' && <span className="source-badge badge-submitted">已投稿</span>}
                    {r.status === 'pending_claim' && <span className="source-badge badge-crawled">已在觅码 · 认领</span>}
                  </label>
                </li>
              ))}
            </ul>
            <Button disabled={!picked} onClick={() => setStep(1)}>下一步</Button>
          </section>
        )}

        {step === 1 && picked && (
          <section className="submit-edit">
            <div className="edit-form">
              <label className="field">
                <span className="field-label">
                  一句话卖点（必填）
                  <span className="tagline-count" aria-live="polite">（{tagline.length}/{TAGLINE_MAX}）</span>
                </span>
                <input name="tagline" autoComplete="off" value={tagline} maxLength={TAGLINE_MAX}
                  onChange={(e) => setTagline(e.target.value)} aria-label="一句话卖点" />
              </label>
              <label className="field">
                <span className="field-label">详细介绍</span>
                <textarea name="intro" autoComplete="off" rows={6} value={intro}
                  onChange={(e) => setIntro(e.target.value)} aria-label="详细介绍" />
              </label>
              <div className="field" role="group" aria-label="分类">
                <span className="field-label">分类</span>
                <div className="cat-pills">
                  {/* 「其他」由自定义分类替代：用户输入任意 tag */}
                  {cats.filter((c) => c !== '其他').map((c) => (
                    <button key={c} className={`cat-pill ${category === c ? 'is-active' : ''}`}
                      aria-pressed={category === c}
                      onClick={() => { setCategory(c); setCustomOpen(false) }}>
                      {c}
                      {aiSuggested === c && <span className="ai-hint" title="AI 推荐">AI</span>}
                    </button>
                  ))}
                  <button className={`cat-pill ${customTag.trim() !== '' && category === customTag.trim() ? 'is-active' : ''}`}
                    aria-pressed={customTag.trim() !== '' && category === customTag.trim()}
                    onClick={() => setCustomOpen(true)}>
                    {customTag.trim() || '自定义'}
                  </button>
                  {customOpen && (
                    <input className="cat-custom-input" autoFocus aria-label="自定义分类"
                      placeholder="输入自定义分类" maxLength={12} value={customTag}
                      onChange={(e) => { setCustomTag(e.target.value); setCategory(e.target.value.trim()) }}
                      onKeyDown={(e) => { if (e.key === 'Enter') e.currentTarget.blur() }}
                      onBlur={() => setCustomOpen(false)} />
                  )}
                </div>
              </div>
              {actionError && <p className="action-error" role="alert">{actionError}</p>}
              <div className="edit-actions">
                <Button variant="secondary" loading={drafting} onClick={() => void aiDraft()}>AI 帮我写</Button>
                <Button disabled={!tagline.trim()} loading={publishing} onClick={() => void publish()}>发布</Button>
              </div>
            </div>
            <div className="edit-preview">
              <p className="preview-label">卡片预览</p>
              {/* 预览卡是静态展示：id 为占位 0，不渲染链接、不参与跳转 */}
              {previewCard && <RepoCard data={previewCard} interactive={false} />}
            </div>
          </section>
        )}

        {step === 2 && (
          <section className="submit-done">
            <span className="done-mark" aria-hidden="true">
              <svg viewBox="0 0 40 40" width="44" height="44">
                <circle cx="20" cy="20" r="17" fill="none" stroke="currentColor" strokeWidth="2.5" />
                <polyline points="13,20.5 18,25.5 27.5,15.5" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round" />
              </svg>
            </span>
            <p className="done-title">已发布，进入首发曝光窗口</p>
            <p className="done-sub">72 小时内你的仓库会获得加权与保底曝光</p>
            <Button onClick={() => navigate(`/user/${user.login}`)}>查看我的主页</Button>
          </section>
        )}
      </main>
    </>
  )
}
