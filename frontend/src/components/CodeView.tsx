// src/components/CodeView.tsx —— 规范 §7.3：等宽 13px + 行号，纯文本；超大文件截断
import type { RepoFile } from '../api/types'
import { blobUrl } from '../lib/githubRaw'
import './CodeView.css'

const MAX_LINES = 2000

export default function CodeView({ file, githubUrl, defaultBranch = 'main' }: { file: RepoFile; githubUrl: string; defaultBranch?: string }) {
  const lines = file.content.split('\n')
  const shown = lines.length > MAX_LINES ? lines.slice(0, MAX_LINES) : lines
  return (
    <div className="code-view">
      <div className="code-head">
        <span className="code-path">{file.path}</span>
        <a className="code-gh-link" href={blobUrl(githubUrl, defaultBranch, file.path)} target="_blank" rel="noreferrer">
          在 GitHub 查看 ↗
        </a>
      </div>
      {/* pre 只允许 phrasing 内容，行容器用 span（display:flex 对 span 同样生效） */}
      <pre className="code-body" data-testid="code-content">
        {shown.map((line, i) => (
          <span key={i} className="code-line">
            <span className="code-ln">{i + 1}</span>
            <span className="code-text">{line || ' '}</span>
          </span>
        ))}
      </pre>
      {lines.length > MAX_LINES && (
        <p className="code-truncated">仅展示前 {MAX_LINES} 行，完整代码请在 GitHub 查看</p>
      )}
    </div>
  )
}
