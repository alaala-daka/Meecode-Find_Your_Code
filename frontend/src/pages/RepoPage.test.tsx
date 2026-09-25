// src/pages/RepoPage.test.tsx
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Route, Routes, useSearchParams } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { FIXTURE_USER } from '../api/fixtures'
import { useAuthStore } from '../store/authStore'
import RepoPage from './RepoPage'

function ParamProbe() {
  const [p] = useSearchParams()
  return <output data-testid="params">{p.toString()}</output>
}

function renderAt(url: string) {
  return render(
    <MemoryRouter initialEntries={[url]}>
      <Routes>
        <Route path="/repo/:id" element={<><RepoPage /><ParamProbe /></>} />
      </Routes>
    </MemoryRouter>
  )
}

describe('RepoPage', () => {
  beforeEach(() => useAuthStore.setState({ user: null }))

  it('信息头：仓库名、卖点、元信息与去 GitHub', async () => {
    renderAt('/repo/1')
    expect(await screen.findByText('mini-agent')).toBeInTheDocument()
    expect(screen.getByText('给 LLM Agent 的最小运行时，200 行可读完')).toBeInTheDocument()
    const gh = screen.getByRole('link', { name: '跳转 GitHub ↗' })
    expect(gh).toHaveAttribute('href', 'https://github.com/alice/mini-agent')
  })

  it('默认展示文件预览，可切换文件', async () => {
    renderAt('/repo/1')
    // README.md 同时出现在文件树与代码区文件名栏，故用 findAllByText
    expect((await screen.findAllByText('README.md')).length).toBeGreaterThanOrEqual(2)
    expect(screen.getByTestId('code-content')).toHaveTextContent('200 行的 LLM Agent 运行时')
    // 目录默认收起：先展开 src 再点 main.py
    await userEvent.click(screen.getByRole('button', { name: /src/ }))
    await userEvent.click(screen.getAllByText('main.py')[0])
    expect(screen.getByTestId('code-content')).toHaveTextContent('from loop import run')
  })

  it('切换到解读面板，后端不可达时显示错误降级', async () => {
    vi.stubEnv('VITE_USE_MOCK', 'false') // 强制真实路径,fetch 不可达 → 错误降级
    vi.stubGlobal('fetch', vi.fn(() => Promise.reject(new TypeError('mock: offline'))))
    renderAt('/repo/1')
    await screen.findAllByText('README.md')
    await userEvent.click(screen.getByRole('tab', { name: '仓库解读' }))
    expect(await screen.findByText('解读服务暂不可用')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: '重试' })).toBeInTheDocument()
    expect(await screen.findByTestId('params')).toHaveTextContent('tab=explain')
    vi.unstubAllGlobals()
    vi.unstubAllEnvs()
  })

  it('未登录点赞触发登录弹层', async () => {
    renderAt('/repo/2')
    await screen.findByText('tinyfetch')
    await userEvent.click(screen.getByRole('button', { name: '点赞' }))
    expect(screen.getByText('用 GitHub 登录')).toBeInTheDocument()
  })

  it('已登录点赞切换激活态', async () => {
    useAuthStore.setState({ user: FIXTURE_USER })
    renderAt('/repo/2')
    await screen.findByText('tinyfetch')
    const btn = screen.getByRole('button', { name: '点赞' })
    await userEvent.click(btn)
    expect(btn).toHaveClass('is-on')
  })

  it('互动态由详情回显：fixture 预置 repo1 点赞、未收藏', async () => {
    renderAt('/repo/1')
    await screen.findByText('mini-agent')
    expect(screen.getByRole('button', { name: '点赞' })).toHaveClass('is-on')
    expect(screen.getByRole('button', { name: '收藏' })).not.toHaveClass('is-on')
    expect(screen.queryByRole('alert')).not.toBeInTheDocument()
  })

  it('仓库不存在显示空态并可回首页', async () => {
    renderAt('/repo/999')
    expect(await screen.findByText('仓库不存在或已下架')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: '回首页' })).toBeInTheDocument()
  })

  it('tab 切换写入 URL', async () => {
    renderAt('/repo/1')
    await screen.findAllByText('README.md')
    await userEvent.click(screen.getByRole('tab', { name: '仓库解读' }))
    expect(await screen.findByTestId('params')).toHaveTextContent('tab=explain')
  })

  it('?file= 深链直接加载指定文件', async () => {
    renderAt('/repo/1?file=src/main.py')
    expect(await screen.findByTestId('code-content')).toHaveTextContent('from loop import run')
  })

  it('点赞失败回滚激活态并提示', async () => {
    useAuthStore.setState({ user: FIXTURE_USER })
    const { api } = await import('../api/client')
    const spy = vi.spyOn(api, 'interact').mockRejectedValueOnce(new Error('boom'))
    // repo/6 未被其他用例点位过，初始态确定（未点赞）
    renderAt('/repo/6')
    await screen.findByText('llm-eval-kit')
    const btn = screen.getByRole('button', { name: '点赞' })
    await userEvent.click(btn)
    await waitFor(() => expect(btn).not.toHaveClass('is-on'))
    expect(screen.getByRole('alert')).toHaveTextContent('操作失败')
    spy.mockRestore()
  })

  it('双列骨架：右栏作者卡常驻，同类推荐来自同分类', async () => {
    renderAt('/repo/1')
    await screen.findByText('mini-agent')
    expect(screen.getByRole('link', { name: '浏览创作者其他仓库' })).toHaveAttribute('href', '/user/alice')
    const rail = await screen.findByLabelText('同类推荐')
    expect(rail.querySelectorAll('.repo-card')).toHaveLength(1)
  })

  it('元信息行带图标计数按钮：心形=likes 数，金星=favorites_count 数', async () => {
    renderAt('/repo/1')
    await screen.findByText('mini-agent')
    expect(screen.getByRole('button', { name: '点赞' })).toHaveTextContent('45')
    expect(screen.getByRole('button', { name: '收藏' })).toHaveTextContent('24')
  })

  it('已登录收藏成功后收藏数即时 +1（可选字段存在时）', async () => {
    useAuthStore.setState({ user: FIXTURE_USER })
    renderAt('/repo/2')
    await screen.findByText('tinyfetch')
    await userEvent.click(screen.getByRole('button', { name: '收藏' }))
    await waitFor(() => expect(screen.getByRole('button', { name: '收藏' })).toHaveTextContent('6'))
  })

  it('自述文件在文件预览之后、讨论区之前', async () => {
    const { container } = renderAt('/repo/1')
    await screen.findAllByText('README.md')
    const readme = container.querySelector('.readme-section')
    const discuss = container.querySelector('.comment-section')
    expect(readme).toBeTruthy()
    expect(discuss).toBeTruthy()
    expect(readme!.compareDocumentPosition(discuss!) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy()
  })

  it('?tab=explain 深链直达解读面板', async () => {
    vi.stubEnv('VITE_USE_MOCK', 'false')
    vi.stubGlobal('fetch', vi.fn(() => Promise.reject(new TypeError('mock: offline'))))
    renderAt('/repo/1?tab=explain')
    expect(await screen.findByText('解读服务暂不可用')).toBeInTheDocument()
    vi.unstubAllGlobals()
    vi.unstubAllEnvs()
  })
})
