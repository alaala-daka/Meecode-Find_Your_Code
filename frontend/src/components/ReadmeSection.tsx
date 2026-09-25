// src/components/ReadmeSection.tsx —— 五项改进 §3.5：自述文件（Markdown 完整渲染）
import { useEffect, useRef, useState } from 'react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import rehypeRaw from 'rehype-raw'
import rehypeSanitize from 'rehype-sanitize'
import type { Components } from 'react-markdown'
import type { RepoTreeItem } from '../api/types'
import { api } from '../api/client'
import { sanitizeSchema } from '../lib/sanitizeSchema'
import './ReadmeSection.css'

const README_RE = /^readme(\.(md|markdown|txt))?$/i
const RAW_BASE = 'https://raw.githubusercontent.com'
const BLOB_BASE = 'https://github.com'

function findReadme(tree: RepoTreeItem[]): string | null {
  const hit = tree.find((n) => n.type === 'file' && README_RE.test(n.name))
  return hit?.path ?? null
}

// repo 内相对路径 → 可达的 GitHub URL；返回 null 表示不可外链（页内锚点等）
function resolveUrl(url: string, base: string, kind: 'asset' | 'link'): string | null {
  if (/^(https?:|mailto:)/i.test(url)) return url
  if (url.startsWith('#')) return null
  const encodePath = (p: string) => p.split('/').map(encodeURIComponent).join('/')
  const clean = url.replace(/^(?:\.?\/)+/, '')
  return kind === 'asset'
    ? `${RAW_BASE}/${base}/${encodePath(clean)}`
    : `${BLOB_BASE}/${base}/blob/${encodePath(clean)}`
}

function buildComponents(base: string): Components {
  return {
    a({ href, children }) {
      const url = href && !href.startsWith('#') ? resolveUrl(href, base, 'link') : null
      if (!url) return <span>{children}</span>
      return <a href={url} target="_blank" rel="noreferrer">{children}</a>
    },
    img({ alt, src }) {
      const url = typeof src === 'string' ? resolveUrl(src, base, 'asset') : null
      if (!url) return <span>{alt || '[图片]'}</span>
      return <img src={url} alt={alt ?? ''} loading="lazy" />
    },
    video({ src, width, height }) {
      const url = typeof src === 'string' ? resolveUrl(src, base, 'asset') : null
      if (!url) return <span>[视频]</span>
      return <video src={url} controls preload="metadata" width={width} height={height} />
    },
  }
}

type Phase = 'loading' | 'ready' | 'missing'

interface Props {
  repoId: number
  tree: RepoTreeItem[]
  fullName: string       // owner/repo：相对路径资源解析到该仓库
  defaultBranch: string
}

export default function ReadmeSection({ repoId, tree, fullName, defaultBranch }: Props) {
  const [phase, setPhase] = useState<Phase>('loading')
  const [content, setContent] = useState('')
  const reqRef = useRef(0)
  const markdownComponents = buildComponents(`${fullName}/${defaultBranch}`)

  useEffect(() => {
    const path = findReadme(tree)
    if (!path) { setPhase('missing'); return }
    const req = ++reqRef.current
    setPhase('loading')
    api.repoFile(repoId, path)
      .then((f) => {
        if (req !== reqRef.current) return
        setContent(f.content)
        setPhase('ready')
      })
      .catch(() => {
        if (req === reqRef.current) setPhase('missing')
      })
  }, [repoId, tree])

  return (
    <section className="readme-section" aria-label="自述文件">
      <h2 className="readme-section-title">自述文件</h2>
      {phase === 'loading' && null}
      {phase === 'missing' && <p className="readme-section-empty">暂无自述</p>}
      {phase === 'ready' && (
        <div className="readme-section-body">
          <ReactMarkdown
            remarkPlugins={[remarkGfm]}
            rehypePlugins={[rehypeRaw, [rehypeSanitize, sanitizeSchema]]}
            components={markdownComponents}
          >
            {content}
          </ReactMarkdown>
        </div>
      )}
    </section>
  )
}
