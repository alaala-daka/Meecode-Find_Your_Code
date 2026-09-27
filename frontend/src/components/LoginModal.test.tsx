// src/components/LoginModal.test.tsx
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { useAuthStore } from '../store/authStore'
import LoginModal from './LoginModal'

describe('LoginModal', () => {
  beforeEach(() => useAuthStore.setState({ user: null }))
  afterEach(() => vi.unstubAllGlobals())

  it('open 时显示登录引导', () => {
    render(<LoginModal open onClose={() => {}} />)
    expect(screen.getByText('用 GitHub 登录')).toBeInTheDocument()
    expect(screen.getByText('登录后即可收藏、点赞与推广仓库')).toBeInTheDocument()
  })
  it('open 时明示 public_repo 权限用途', () => {
    render(<LoginModal open onClose={() => {}} />)
    expect(screen.getByText('登录将获得 GitHub public_repo 权限，仅用于为你点星/取消星')).toBeInTheDocument()
  })
  it('closed 时不渲染', () => {
    render(<LoginModal open={false} onClose={() => {}} />)
    expect(screen.queryByText('用 GitHub 登录')).not.toBeInTheDocument()
  })
  it('点击登录跳转 GitHub OAuth 并关闭', async () => {
    const assign = vi.fn()
    vi.stubGlobal('location', { assign })
    const onClose = vi.fn()
    render(<LoginModal open onClose={onClose} />)
    await userEvent.click(screen.getByText('用 GitHub 登录'))
    expect(assign).toHaveBeenCalledWith('/api/auth/github')
    expect(onClose).toHaveBeenCalled()
  })
  it('打开时焦点移入弹层', () => {
    render(<LoginModal open onClose={() => {}} />)
    expect(screen.getByRole('button', { name: '用 GitHub 登录' })).toHaveFocus()
  })
  it('Esc 关闭弹层', async () => {
    const onClose = vi.fn()
    render(<LoginModal open onClose={onClose} />)
    await userEvent.keyboard('{Escape}')
    expect(onClose).toHaveBeenCalled()
  })
  it('有关闭按钮并响应点击', async () => {
    const onClose = vi.fn()
    render(<LoginModal open onClose={onClose} />)
    await userEvent.click(screen.getByRole('button', { name: '关闭登录弹层' }))
    expect(onClose).toHaveBeenCalled()
  })
  it('打开时锁定滚动，关闭后恢复', () => {
    const { unmount } = render(<LoginModal open onClose={() => {}} />)
    expect(document.body.style.overflow).toBe('hidden')
    unmount()
    expect(document.body.style.overflow).toBe('')
  })
})
