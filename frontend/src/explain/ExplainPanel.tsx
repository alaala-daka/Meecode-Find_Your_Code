/** 仓库解读面板:进入 tab 即自动以仓库为根建图(spec §5.2)。
 * 编排自原型 WorkspacePage——去除输入阶段与页面装饰,图引擎/面板原样复用。 */
import { useCallback, useEffect, useState } from 'react'
import type { RepoDetail } from '../api/types'
import { useIsMobile } from '../utils/useIsMobile'
import { api } from './api/client'
import { GraphCanvas } from './components/GraphCanvas'
import { PracticeBar } from './components/PracticeBar'
import { SettingsPanel } from './components/SettingsPanel'
import { Toasts } from './components/Toasts'
import { ReaderPanel } from './components/reader/ReaderPanel'
import { openReaderFromTopbar } from './graph/controller'
import { useGraphStore } from './store/graphStore'
import { useReaderStore } from './store/readerStore'
import { useSessionStore } from './store/sessionStore'
import { useUiStore } from './store/uiStore'
import './explain-tokens.css'
import './explain.css'

type Stage = 'loading' | 'graph' | 'error'

/** https://github.com/owner/repo(.git) → owner/repo */
export function repoFullName(githubUrl: string): string {
  const raw = githubUrl.trim()
  const path = raw
    .replace(/^https?:\/\/github\.com\//i, '')
    .replace(/\.git$/, '')
    .replace(/^\/+|\/+$/g, '')
  return path
}

interface Props {
  repo: RepoDetail
}

export default function ExplainPanel({ repo }: Props) {
  const [stage, setStage] = useState<Stage>('loading')
  const [errorMsg, setErrorMsg] = useState('')
  const full_name = repoFullName(repo.github_url)

  const rootId = useGraphStore((s) => s.rootId)
  const path = useSessionStore((s) => s.path)
  const mode = useSessionStore((s) => s.mode)
  const enterPractice = useSessionStore((s) => s.enterPractice)
  const resetSession = useSessionStore((s) => s.resetSession)
  const resetGraph = useGraphStore((s) => s.reset)
  const toggleSettings = useUiStore((s) => s.toggleSettings)
  const readerOpen = useReaderStore((s) => s.open)
  const isMobile = useIsMobile()
  const mobileReading = isMobile && readerOpen // 移动端整屏阅读态:图 ⇄ 阅读器互斥切换

  const build = useCallback(
    async (fullName: string, branch: string | null) => {
      setStage('loading')
      setErrorMsg('')
      useReaderStore.getState().reset()
      resetGraph()
      resetSession()
      try {
        const sessionId = await useSessionStore.getState().ensureSession()
        const result = await api.repoRoot(sessionId, { full_name: fullName, default_branch: branch })
        useGraphStore.getState().setRoot(result.node)
        if (result.children.length > 0) {
          useGraphStore.getState().addChildren(result.node.id, result.children, result.edges)
        }
        setStage('graph')
      } catch (err) {
        setErrorMsg(err instanceof Error ? err.message : '解读服务暂不可用')
        setStage('error')
      }
    },
    [resetGraph, resetSession],
  )

  useEffect(() => {
    void build(full_name, repo.default_branch || null)
  }, [build, full_name, repo.default_branch])

  return (
    <div className={`explain-root${mobileReading ? ' explain-root--reading' : ''}`}>
      {stage === 'loading' && (
        <div className="explain-loading" role="status" aria-label="正在生成仓库解读">
          <p className="explain-loading-title">AI 正在阅读这个仓库…</p>
          <p className="explain-loading-sub">拉取 README 与目录结构，生成解读图</p>
        </div>
      )}
      {stage === 'error' && (
        <div className="explain-error" role="alert">
          <p className="explain-error-title">解读服务暂不可用</p>
          <p className="explain-error-sub">{errorMsg}</p>
          <button className="explain-retry" onClick={() => void build(full_name, repo.default_branch || null)}>
            重试
          </button>
        </div>
      )}
      {stage === 'graph' && rootId && (
        <>
          <div className="explain-toolbar">
            {mode === 'explore' && (
              <button
                className="explain-tool-btn"
                onClick={enterPractice}
                disabled={path.length === 0}
                title={path.length === 0 ? '先展开几个节点，再来练习' : '沿着你的探索轨迹回忆'}
              >
                练习模式
              </button>
            )}
            {/* 齿轮图形取自 feedback/setting.svg，改用 currentColor 以适配工具栏配色 */}
            <button className="explain-tool-btn" onClick={toggleSettings} aria-label="设置" title="设置">
              <svg width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
                <circle cx="12" cy="12" r="3" />
                <path d="M2 12.8794V11.1194C2 10.0794 2.85 9.21945 3.9 9.21945C5.71 9.21945 6.45 7.93945 5.54 6.36945C5.02 5.46945 5.33 4.29945 6.24 3.77945L7.97 2.78945C8.76 2.31945 9.78 2.59945 10.25 3.38945L10.36 3.57945C11.26 5.14945 12.74 5.14945 13.65 3.57945L13.76 3.38945C14.23 2.59945 15.25 2.31945 16.04 2.78945L17.77 3.77945C18.68 4.29945 18.99 5.46945 18.47 6.36945C17.56 7.93945 18.3 9.21945 20.11 9.21945C21.15 9.21945 22.01 10.0694 22.01 11.1194V12.8794C22.01 13.9194 21.16 14.7794 20.11 14.7794C18.3 14.7794 17.56 16.0594 18.47 17.6294C18.99 18.5394 18.68 19.6994 17.77 20.2194L16.04 21.2094C15.25 21.6794 14.23 21.3994 13.76 20.6094L13.65 20.4194C12.75 18.8494 11.27 18.8494 10.36 20.4194L10.25 20.6094C9.78 21.3994 8.76 21.6794 7.97 21.2094L6.24 20.2194C5.33 19.6994 5.02 18.5294 5.54 17.6294C6.45 16.0594 5.71 14.7794 3.9 14.7794C2.85 14.7794 2 13.9194 2 12.8794Z" />
              </svg>
            </button>
            <button
              className={`explain-tool-btn${readerOpen ? ' active' : ''}`}
              onClick={() => void openReaderFromTopbar()}
              aria-label={readerOpen ? '收起阅读器' : '展开阅读器'}
              aria-pressed={readerOpen}
              title={readerOpen ? '收起阅读器' : '展开阅读器'}
              disabled={mode === 'practice'}
            >
              <svg width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
                <path d="M12 6c-1.8-1.6-4.2-2-7-2v14c2.8 0 5.2.4 7 2 1.8-1.6 4.2-2 7-2V4c-2.8 0-5.2.4-7 2z" />
                <path d="M12 6v14" />
              </svg>
            </button>
          </div>
          {mode === 'practice' && <PracticeBar />}
          <GraphCanvas />
        </>
      )}
      <SettingsPanel />
      <ReaderPanel />
      <Toasts />
    </div>
  )
}
