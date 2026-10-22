// src/components/TopBar.test.tsx
import { act, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { FIXTURE_USER } from '../api/fixtures'
import { useAuthStore } from '../store/authStore'
import { useNotificationStore } from '../store/notificationStore'
import TopBar from './TopBar'

const navigateSpy = vi.fn()
vi.mock('react-router-dom', async () => {
  const actual = await vi.importActual<typeof import('react-router-dom')>('react-router-dom')
  return { ...actual, useNavigate: () => navigateSpy }
})

function renderTopBar() {
  return render(
    <MemoryRouter>
      <Routes>
        <Route path="*" element={<TopBar />} />
      </Routes>
    </MemoryRouter>
  )
}

describe('TopBar', () => {
  beforeEach(() => {
    useAuthStore.setState({ user: null })
    navigateSpy.mockClear()
  })

  it('搜索提交跳转搜索结果页', async () => {
    renderTopBar()
    const input = screen.getByPlaceholderText('搜索仓库、标签、一句话卖点…')
    await userEvent.type(input, 'agent')
    await userEvent.keyboard('{Enter}')
    expect(navigateSpy).toHaveBeenCalledWith('/search?q=agent')
  })

  it('未登录显示登录入口，登录后显示头像', () => {
    renderTopBar()
    expect(screen.getByText('登录')).toBeInTheDocument()
    act(() => useAuthStore.setState({ user: FIXTURE_USER }))
    expect(screen.getByLabelText('个人主页')).toBeInTheDocument()
    expect(screen.queryByText('登录')).not.toBeInTheDocument()
  })

  it('未登录点击推广弹出登录弹层（规范 §8.3）', async () => {
    renderTopBar()
    await userEvent.click(screen.getByRole('button', { name: /推广我的仓库/ }))
    expect(screen.getByText('用 GitHub 登录')).toBeInTheDocument()
    expect(navigateSpy).not.toHaveBeenCalled()
  })

  it('登录后推广按钮跳转投稿页', async () => {
    useAuthStore.setState({ user: FIXTURE_USER })
    renderTopBar()
    await userEvent.click(screen.getByRole('button', { name: /推广我的仓库/ }))
    expect(navigateSpy).toHaveBeenCalledWith('/submit')
  })

  it('浏览历史：已登录跳个人页历史 tab', async () => {
    useAuthStore.setState({ user: FIXTURE_USER })
    renderTopBar()
    await userEvent.click(screen.getByLabelText('浏览历史'))
    expect(navigateSpy).toHaveBeenCalledWith('/user/alice?tab=history')
  })

  it('搜索页顶栏保留查询词（规范 §7.2）', () => {
    render(
      <MemoryRouter initialEntries={['/search?q=agent']}>
        <Routes>
          <Route path="*" element={<TopBar />} />
        </Routes>
      </MemoryRouter>,
    )
    expect(screen.getByRole('textbox', { name: '搜索' })).toHaveValue('agent')
  })

  it('导航高亮仅首页', () => {
    render(
      <MemoryRouter initialEntries={['/repo/1']}>
        <Routes>
          <Route path="*" element={<TopBar />} />
        </Routes>
      </MemoryRouter>,
    )
    expect(screen.getByRole('link', { name: '首页' })).not.toHaveClass('is-current')
  })

  it('铃铛显示未读红点且可展开菜单', async () => {
    useAuthStore.setState({ user: FIXTURE_USER })   // 未登录会被守卫拦下弹登录框
    useNotificationStore.setState({ count: 2 })
    const { api } = await import('../api/client')
    vi.spyOn(api, 'replyNotifications').mockResolvedValue({
      items: [{ feedback_id: 3, feedback_body_preview: '原问题', reply_id: 9,
                reply_body_preview: '已修复', created_at: 1_700_000_000 }],
      total: 1,
    })
    renderTopBar()
    const bell = screen.getByRole('button', { name: '反馈回复通知' })
    expect(bell).toHaveAttribute('aria-expanded', 'false')
    await userEvent.click(bell)                      // 该文件既有 import 是 userEvent，没有 fireEvent
    expect(bell).toHaveAttribute('aria-expanded', 'true')
    expect(await screen.findByText('已修复')).toBeInTheDocument()
    expect(screen.getByRole('link', { name: '查看全部反馈 →' })).toHaveAttribute(
      'href', '/my/feedback')
  })

  it('未登录点铃铛弹登录框而非菜单（UI 约束 §1.8）', async () => {
    renderTopBar()
    await userEvent.click(screen.getByRole('button', { name: '反馈回复通知' }))
    expect(screen.getByText('用 GitHub 登录')).toBeInTheDocument()
    expect(screen.queryByRole('menu')).not.toBeInTheDocument()
  })
})

describe('TopBar 手机端（≤720px）', () => {
  beforeEach(() => {
    // 手机视口：jsdom 无真实媒体查询，按 useIsMobile 约定桩出「命中 720px 断点」
    vi.stubGlobal('matchMedia', (query: string) => ({
      matches: query.includes('max-width: 720px'),
      media: query,
      onchange: null,
      addEventListener: () => {},
      removeEventListener: () => {},
      addListener: () => {},
      removeListener: () => {},
      dispatchEvent: () => false,
    }))
    useAuthStore.setState({ user: null })
    useNotificationStore.setState({ count: 0 })
    navigateSpy.mockClear()
  })

  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('搜索框收为入口按钮，点击跳搜索中间页', async () => {
    renderTopBar()
    expect(screen.queryByRole('textbox', { name: '搜索' })).not.toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: '搜索' }))
    expect(navigateSpy).toHaveBeenCalledWith('/search-entry')
  })

  it('不渲染反馈铃铛与浏览历史（宽度让位搜索入口）', () => {
    useNotificationStore.setState({ count: 2 })
    renderTopBar()
    expect(screen.queryByRole('button', { name: '反馈回复通知' })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: '浏览历史' })).not.toBeInTheDocument()
  })

  it('反馈图标与登录入口仍保留', () => {
    renderTopBar()
    expect(screen.getByRole('button', { name: '反馈' })).toBeInTheDocument()
    expect(screen.getByText('登录')).toBeInTheDocument()
  })
})
