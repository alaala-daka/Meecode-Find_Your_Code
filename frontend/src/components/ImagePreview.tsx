// src/components/ImagePreview.tsx —— 图片预览：raw 直链 <img>（SVG 走 img 通道不执行脚本），5MB 上限，失败降级
import { useState } from 'react'
import { blobUrl, rawUrlFor } from '../lib/githubRaw'
import './CodeView.css' // 复用 code-head/code-path/code-gh-link 头部样式
import './ImagePreview.css'

const MAX_IMAGE_BYTES = 5 * 1024 * 1024

function fmtMb(bytes: number): string {
  return (bytes / 1024 / 1024).toFixed(1)
}

export default function ImagePreview({ path, fullName, defaultBranch, githubUrl, size }: {
  path: string
  fullName: string
  defaultBranch: string
  githubUrl: string
  size?: number
}) {
  const [failedPath, setFailedPath] = useState<string | null>(null)
  const bytes = size ?? 0
  const tooLarge = bytes > MAX_IMAGE_BYTES
  const failed = failedPath === path // 失败态绑定 path：切换图片即复位，不跨 path 残留
  const ghLink = blobUrl(githubUrl, defaultBranch, path)
  return (
    <div className="code-view image-preview">
      <div className="code-head">
        <span className="code-path">{path}</span>
        <a className="code-gh-link" href={ghLink} target="_blank" rel="noreferrer">在 GitHub 查看 ↗</a>
      </div>
      {tooLarge ? (
        <p className="image-fallback">
          文件过大（{fmtMb(bytes)} MB），<a href={ghLink} target="_blank" rel="noreferrer">去 GitHub 查看 ↗</a>
        </p>
      ) : failed ? (
        <p className="image-fallback">
          图片加载失败，<a href={ghLink} target="_blank" rel="noreferrer">去 GitHub 查看 ↗</a>
        </p>
      ) : (
        <div className="image-stage">
          <img src={rawUrlFor(fullName, defaultBranch, path)} alt={path} loading="lazy" onError={() => setFailedPath(path)} />
        </div>
      )}
    </div>
  )
}
