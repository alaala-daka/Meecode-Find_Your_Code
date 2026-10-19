// src/components/ReadmeSection.test.tsx
import { render, screen } from '@testing-library/react'
import { describe, expect, it, vi, afterEach } from 'vitest'
import type { RepoTreeItem } from '../api/types'
import ReadmeSection from './ReadmeSection'

const TREE_WITH_README: RepoTreeItem[] = [
  { name: 'README.md', path: 'README.md', type: 'file' },
  { name: 'src', path: 'src', type: 'dir', children: [] },
]

describe('ReadmeSection', () => {
  afterEach(() => vi.restoreAllMocks())

  it('定位 README.md 并完整渲染 Markdown（GFM 标题）', async () => {
    render(<ReadmeSection repoId={1} tree={TREE_WITH_README} fullName="owner/repo" defaultBranch="main" />)
    expect(await screen.findByRole('heading', { level: 1, name: 'mini-agent' })).toBeInTheDocument()
    expect(screen.getByText(/200 行的 LLM Agent 运行时/)).toBeInTheDocument()
  })

  it('README 内嵌 HTML：消毒后渲染为元素，script 被剔除', async () => {
    const { api } = await import('../api/client')
    vi.spyOn(api, 'repoFile').mockResolvedValueOnce({
      path: 'README.md',
      content: '<div align="center"><a href="https://example.com">badge</a>'
        + '<img src="assets/演示 截图.png" alt="演示" /></div><script>alert(1)</script>',
    })
    render(<ReadmeSection repoId={1} tree={TREE_WITH_README} fullName="owner/repo" defaultBranch="main" />)
    expect(await screen.findByRole('link', { name: 'badge' })).toHaveAttribute('href', 'https://example.com')
    expect(screen.getByAltText('演示')).toHaveAttribute(
      'src',
      'https://raw.githubusercontent.com/owner/repo/main/assets/%E6%BC%94%E7%A4%BA%20%E6%88%AA%E5%9B%BE.png',
    )
    expect(screen.queryByText('alert(1)')).not.toBeInTheDocument()
  })

  it('树中没有 README：立即显示「暂无自述」且不发请求', async () => {
    const { api } = await import('../api/client')
    const spy = vi.spyOn(api, 'repoFile')
    render(<ReadmeSection repoId={1} tree={[{ name: 'main.py', path: 'main.py', type: 'file' }]} fullName="owner/repo" defaultBranch="main" />)
    expect(screen.getByText('暂无自述')).toBeInTheDocument()
    expect(spy).not.toHaveBeenCalled()
  })

  it('读取失败同样降级为「暂无自述」', async () => {
    const { api } = await import('../api/client')
    vi.spyOn(api, 'repoFile').mockRejectedValueOnce(new Error('boom'))
    render(<ReadmeSection repoId={1} tree={TREE_WITH_README} fullName="owner/repo" defaultBranch="main" />)
    expect(await screen.findByText('暂无自述')).toBeInTheDocument()
  })

  it('README 相对链接解析为 GitHub canonical 深链（blob/<ref>/<path>）', async () => {
    const { api } = await import('../api/client')
    vi.spyOn(api, 'repoFile').mockResolvedValueOnce({
      path: 'README.md',
      content: '详见 [文档](docs/使用说明.md)',
    })
    render(<ReadmeSection repoId={1} tree={TREE_WITH_README} fullName="owner/repo" defaultBranch="main" />)
    expect(await screen.findByRole('link', { name: '文档' }))
      .toHaveAttribute('href', 'https://github.com/owner/repo/blob/main/docs/%E4%BD%BF%E7%94%A8%E8%AF%B4%E6%98%8E.md')
  })
})
