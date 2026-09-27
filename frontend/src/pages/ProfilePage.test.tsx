// src/pages/ProfilePage.test.tsx
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { FIXTURE_USER } from '../api/fixtures'
import type { CurrentUser } from '../api/types'
import { useAuthStore } from '../store/authStore'
import ProfilePage from './ProfilePage'

function renderAt(url: string) {
  return render(
    <MemoryRouter initialEntries={[url]}>
      <Routes>
        <Route path="/user/:login" element={<ProfilePage />} />
      </Routes>
    </MemoryRouter>
  )
}

describe('ProfilePage', () => {
  beforeEach(() => {
    useAuthStore.setState({ user: null })
    vi.restoreAllMocks()
  })

  it('头部整体位于横幅内', async () => {
    renderAt('/user/alice')
    // login 在主页标题与本人仓库卡作者名双渲染（同 Task 8 findAllByText 约定）
    expect((await screen.findAllByText('alice')).length).toBeGreaterThanOrEqual(2)
    expect(screen.getByText('在写小而可读的系统软件。')).toBeInTheDocument()
    expect(screen.getByText('获赞星')).toBeInTheDocument()
    expect(screen.getByRole('img', { name: 'alice 的头像' })).toBeInTheDocument()
    expect(screen.getByRole('img', { name: 'alice 的头像' }).closest('.profile-banner')).not.toBeNull()
    // 横幅不再是纯装饰：aria-hidden 应已被移除
    expect(document.querySelector('.profile-banner')!.getAttribute('aria-hidden')).toBeNull()
  })

  it('本人视图可就地编辑签名', async () => {
    useAuthStore.setState({ user: FIXTURE_USER })
    renderAt('/user/alice')
    await screen.findAllByText('alice')
    await userEvent.click(screen.getByLabelText('编辑签名'))
    const input = screen.getByDisplayValue('在写小而可读的系统软件。')
    await userEvent.clear(input)
    await userEvent.type(input, '新的签名')
    await userEvent.tab() // 失焦保存
    expect(await screen.findByText('新的签名')).toBeInTheDocument()
  })

  it('他人视图无编辑入口', async () => {
    useAuthStore.setState({ user: FIXTURE_USER })
    renderAt('/user/bob')
    await screen.findAllByText('bob')
    expect(screen.queryByLabelText('编辑签名')).not.toBeInTheDocument()
  })

  it('tab 切换到收藏夹显示收藏内容', async () => {
    renderAt('/user/alice?tab=favs')
    // 无封面卡：仓库名只在标题链接渲染一次（fixture 收藏为 id 3）
    expect((await screen.findAllByText('rust-kv')).length).toBeGreaterThanOrEqual(1)
  })

  it('浏览历史 tab 由 URL 参数驱动', async () => {
    renderAt('/user/alice?tab=history')
    expect((await screen.findAllByText('tinyfetch')).length).toBeGreaterThanOrEqual(1)
  })

  it('加载失败显示错误条与重试（规范 §8.2）', async () => {
    const { api } = await import('../api/client')
    const spy = vi.spyOn(api, 'userProfile').mockRejectedValue(new Error('boom'))
    renderAt('/user/alice')
    expect(await screen.findByText('主页加载失败')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: '重试' })).toBeInTheDocument()
    spy.mockRestore()
  })

  it('本人仓库可下架', async () => {
    vi.spyOn(window, 'confirm').mockReturnValue(true)
    useAuthStore.setState({ user: FIXTURE_USER })
    renderAt('/user/alice')
    // 仓库名在封面 SVG 与标题双渲染（同 Task 8 约定）
    await screen.findAllByText('mini-agent')
    await userEvent.click(screen.getByRole('button', { name: '下架' }))
    expect(await screen.findByText('你还没有推广过仓库')).toBeInTheDocument()
  })

  it('Esc 取消编辑签名', async () => {
    useAuthStore.setState({ user: FIXTURE_USER })
    renderAt('/user/alice')
    await screen.findAllByText('alice')
    await userEvent.click(screen.getByLabelText('编辑签名'))
    const input = screen.getByDisplayValue('在写小而可读的系统软件。')
    await userEvent.clear(input)
    await userEvent.type(input, '不保存的签名')
    await userEvent.keyboard('{Escape}')
    expect(screen.getByText('在写小而可读的系统软件。')).toBeInTheDocument()
    expect(screen.queryByDisplayValue('不保存的签名')).not.toBeInTheDocument()
  })

  it('未授权点星时无断开入口', async () => {
    useAuthStore.setState({ user: FIXTURE_USER })  // UserProfile 形状，无 gh_star_authed
    renderAt('/user/alice')
    await screen.findAllByText('alice')
    expect(screen.queryByRole('button', { name: /GitHub 点星已连接/ })).not.toBeInTheDocument()
  })

  it('已授权点星：本人视图显示断开入口，点击后消失', async () => {
    useAuthStore.setState({ user: { ...FIXTURE_USER, id: 1, gh_star_authed: true } as CurrentUser })
    renderAt('/user/alice')
    await screen.findAllByText('alice')
    await userEvent.click(screen.getByRole('button', { name: /GitHub 点星已连接/ }))
    await waitFor(() =>
      expect(screen.queryByRole('button', { name: /GitHub 点星已连接/ })).not.toBeInTheDocument())
  })
})
