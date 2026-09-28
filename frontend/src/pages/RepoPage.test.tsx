// src/pages/RepoPage.test.tsx
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Route, Routes, useSearchParams } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { FIXTURE_USER } from '../api/fixtures'
import type { CurrentUser } from '../api/types'
import { useAuthStore } from '../store/authStore'
import RepoPage from './RepoPage'

function ParamProbe() {
  const [p] = useSearchParams()
  // 用 span：output 有隐式 role="status"，会与 Toast/提示条的 status 查询相撞
  return <span data-testid="params">{p.toString()}</span>
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
  beforeEach(async () => {
    useAuthStore.setState({ user: null })
    // mock client 是模块单例，收藏态跨用例串味：归位 fixture 预置（repo3 已收藏、repo5 未收藏）
    const { api } = await import('../api/client')
    const [r3, r5] = await Promise.all([api.repo(3), api.repo(5)])
    if (!r3.favorited) await api.interact(3, 'favorite', true, false)
    if (r5.favorited) await api.interact(5, 'favorite', false, false)
  })

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

  it('收藏后无 token：出授权提示条与链接，且不自动消失', async () => {
    useAuthStore.setState({ user: FIXTURE_USER })
    renderAt('/repo/5')
    await screen.findByText('dot-snap')
    await userEvent.click(screen.getByRole('button', { name: '收藏' }))
    expect(await screen.findByText(/授权后自动在 GitHub 点星/)).toBeInTheDocument()
    const link = screen.getByRole('link', { name: /授权 GitHub 点星/ })
    expect(link).toHaveAttribute('href', '/api/auth/github')
    expect(link).toHaveAttribute('title', expect.stringContaining('public_repo'))
    expect(link).toHaveAttribute('aria-label', expect.stringContaining('将获得 public_repo 权限，仅用于在 GitHub 上为你点星/取消星'))
  })

  it('收藏 pending：提示稍后自动重试文案', async () => {
    useAuthStore.setState({ user: FIXTURE_USER })
    const { api } = await import('../api/client')
    const spy = vi.spyOn(api, 'interact').mockResolvedValueOnce({ active: true, sync: 'pending' })
    renderAt('/repo/4')
    await screen.findByText('csv-crunch')
    await userEvent.click(screen.getByRole('button', { name: '收藏' }))
    expect(await screen.findByText(/稍后自动重试/)).toBeInTheDocument()
    spy.mockRestore()
  })

  it('未授权点取消 → 弹窗出现且本地收藏未动', async () => {
    useAuthStore.setState({ user: FIXTURE_USER })
    renderAt('/repo/3')                      // fixture repo3 预置已收藏
    await screen.findByText('rust-kv')
    await userEvent.click(screen.getByRole('button', { name: '收藏' }))
    expect(await screen.findByRole('dialog')).toHaveTextContent('取消收藏将同步取消 GitHub 星')
    expect(screen.getByRole('button', { name: '收藏' })).toHaveClass('is-on')  // 本地未动
  })

  it('弹窗【仅取消本地收藏】→ ghSync:false，提示星保留', async () => {
    useAuthStore.setState({ user: FIXTURE_USER })
    renderAt('/repo/3')
    await screen.findByText('rust-kv')
    await userEvent.click(screen.getByRole('button', { name: '收藏' }))
    await userEvent.click(await screen.findByRole('button', { name: '仅取消本地收藏' }))
    expect(await screen.findByText(/已取消收藏，GitHub 星保留/)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: '收藏' })).not.toHaveClass('is-on')
  })

  it('弹窗关闭 → 收藏原样不动', async () => {
    useAuthStore.setState({ user: FIXTURE_USER })
    renderAt('/repo/3')
    await screen.findByText('rust-kv')
    await userEvent.click(screen.getByRole('button', { name: '收藏' }))
    await userEvent.keyboard('{Escape}')
    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument())
    expect(screen.getByRole('button', { name: '收藏' })).toHaveClass('is-on')
  })

  it('已授权取消收藏 → 直接撤星，unstarred 静默', async () => {
    const { api } = await import('../api/client')
    const spy = vi.spyOn(api, 'interact').mockResolvedValue({ active: false, sync: 'unstarred' })
    useAuthStore.setState({ user: { ...FIXTURE_USER, id: 1, gh_star_authed: true } as CurrentUser })
    renderAt('/repo/3')
    await screen.findByText('rust-kv')
    await userEvent.click(screen.getByRole('button', { name: '收藏' }))
    await waitFor(() => expect(screen.getByRole('button', { name: '收藏' })).not.toHaveClass('is-on'))
    expect(spy).toHaveBeenCalledWith(3, 'favorite', false, true)
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
    expect(screen.queryByRole('status')).not.toBeInTheDocument()
    spy.mockRestore()
  })

  it('收藏方向 skipped → Toast 仓库消失', async () => {
    const { api } = await import('../api/client')
    const spy = vi.spyOn(api, 'interact').mockResolvedValue({ active: true, sync: 'skipped' })
    useAuthStore.setState({ user: FIXTURE_USER })
    renderAt('/repo/5')
    await screen.findByText('dot-snap')
    await userEvent.click(screen.getByRole('button', { name: '收藏' }))
    expect(await screen.findByRole('status')).toHaveTextContent('仓库消失了')
    spy.mockRestore()
  })

  it('补救模式【仅取消本地收藏】→ favorites_count 只扣一次', async () => {
    useAuthStore.setState({ user: { ...FIXTURE_USER, id: 1, gh_star_authed: true } as CurrentUser })
    const { api } = await import('../api/client')
    const spy = vi.spyOn(api, 'interact')
      .mockResolvedValueOnce({ active: false, sync: 'need_auth' })
      .mockResolvedValueOnce({ active: false, sync: 'kept' })
    renderAt('/repo/3')
    await screen.findByText('rust-kv')
    const favBtn = screen.getByRole('button', { name: '收藏' })
    const before = Number(favBtn.textContent)
    await userEvent.click(favBtn)                 // 已授权撤星 → need_auth → 补救弹窗（已乐观扣过一次）
    await screen.findByRole('dialog')
    await userEvent.click(screen.getByRole('button', { name: '仅取消本地收藏' }))
    expect(await screen.findByText(/已取消收藏，GitHub 星保留/)).toBeInTheDocument()
    expect(Number(screen.getByRole('button', { name: '收藏' }).textContent)).toBe(before - 1)  // 不得双扣
    expect(spy).toHaveBeenNthCalledWith(2, 3, 'favorite', false, false)
    spy.mockRestore()
  })

  it('补救模式【仅取消本地收藏】第二次调用失败 → 星钮保持熄灭', async () => {
    useAuthStore.setState({ user: { ...FIXTURE_USER, id: 1, gh_star_authed: true } as CurrentUser })
    const { api } = await import('../api/client')
    const spy = vi.spyOn(api, 'interact')
      .mockResolvedValueOnce({ active: false, sync: 'need_auth' })
      .mockRejectedValueOnce(new Error('boom'))
    renderAt('/repo/3')
    await screen.findByText('rust-kv')
    await userEvent.click(screen.getByRole('button', { name: '收藏' }))   // 已授权撤星 → need_auth → 补救弹窗
    await screen.findByRole('dialog')
    await userEvent.click(screen.getByRole('button', { name: '仅取消本地收藏' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('操作失败')
    expect(screen.getByRole('button', { name: '收藏' })).not.toHaveClass('is-on')  // 首次取消已落库，不翻回
    expect(spy).toHaveBeenNthCalledWith(2, 3, 'favorite', false, false)
    spy.mockRestore()
  })
})
