// src/components/CommentSection.test.tsx
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi, afterEach } from 'vitest'
import type { CurrentUser } from '../api/types'
import CommentSection from './CommentSection'

let mockUser: CurrentUser | null = {
  id: 9, login: 'me', avatar_url: 'https://a/x', bio: '',
}
vi.mock('../store/authStore', () => ({
  useAuthStore: (selector: (s: { user: CurrentUser | null }) => unknown) =>
    selector({ user: mockUser }),
}))

const FIXTURE = {
  items: [
    {
      id: 1, repo_id: 1, user_id: 2, user_login: 'alice', user_avatar: 'https://a/a',
      parent_id: null, content: '一楼', status: 'visible' as const,
      created_at: 1, created_at_iso: '2026-01-01T00:00:00+00:00',
    },
    {
      id: 2, repo_id: 1, user_id: 3, user_login: 'bob', user_avatar: '',
      parent_id: 1, content: '回复一楼', status: 'visible' as const,
      created_at: 2, created_at_iso: '2026-01-01T00:01:00+00:00',
    },
    {
      id: 3, repo_id: 1, user_id: 9, user_login: 'me', user_avatar: '',
      parent_id: null, content: '审核中内容', status: 'pending' as const,
      created_at: 3, created_at_iso: '2026-01-01T00:02:00+00:00',
    },
  ],
  total: 2,
}

describe('CommentSection', () => {
  beforeEach(() => {
    mockUser = { id: 9, login: 'me', avatar_url: 'https://a/x', bio: '' }
  })
  afterEach(() => vi.restoreAllMocks())

  it('平铺数据按 parent_id 渲染两层', async () => {
    const { api } = await import('../api/client')
    vi.spyOn(api, 'comments').mockResolvedValue(FIXTURE)
    render(<CommentSection repoId={1} canModerate={false} onNeedLogin={() => {}} />)
    expect(await screen.findByText('一楼')).toBeInTheDocument()
    expect(screen.getByText('回复一楼')).toBeInTheDocument()
  })

  it('pending 评论带「审核中」标记', async () => {
    const { api } = await import('../api/client')
    vi.spyOn(api, 'comments').mockResolvedValue(FIXTURE)
    render(<CommentSection repoId={1} canModerate={false} onNeedLogin={() => {}} />)
    expect(await screen.findByText('审核中内容')).toBeInTheDocument()
    expect(screen.getByText('审核中')).toBeInTheDocument()
  })

  it('匿名点发送触发 onNeedLogin 且不发请求', async () => {
    mockUser = null
    const { api } = await import('../api/client')
    vi.spyOn(api, 'comments').mockResolvedValue(FIXTURE)
    const spy = vi.spyOn(api, 'postComment')
    const onNeedLogin = vi.fn()
    render(<CommentSection repoId={1} canModerate={false} onNeedLogin={onNeedLogin} />)
    await screen.findByText('一楼')
    await userEvent.type(screen.getByRole('textbox'), 'hi')
    await userEvent.click(screen.getByRole('button', { name: '发送' }))
    expect(onNeedLogin).toHaveBeenCalled()
    expect(spy).not.toHaveBeenCalled()
  })

  it('发送成功乐观插入 pending 项', async () => {
    const { api } = await import('../api/client')
    vi.spyOn(api, 'comments').mockResolvedValue(FIXTURE)
    vi.spyOn(api, 'postComment').mockResolvedValue({
      id: 99, repo_id: 1, user_id: 9, user_login: 'me', user_avatar: '',
      parent_id: null, content: '新评论', status: 'pending',
      created_at: 9, created_at_iso: 'x',
    })
    render(<CommentSection repoId={1} canModerate={false} onNeedLogin={() => {}} />)
    await screen.findByText('一楼')
    await userEvent.type(screen.getByRole('textbox'), '新评论')
    await userEvent.click(screen.getByRole('button', { name: '发送' }))
    expect(await screen.findByText('新评论')).toBeInTheDocument()
  })

  it('canModerate 时显示隐藏按钮，点击即调 hideComment', async () => {
    const { api } = await import('../api/client')
    vi.spyOn(api, 'comments').mockResolvedValue(FIXTURE)
    const hideSpy = vi.spyOn(api, 'hideComment').mockResolvedValue(undefined)
    render(<CommentSection repoId={1} canModerate onNeedLogin={() => {}} />)
    await screen.findByText('一楼')
    await userEvent.click(screen.getAllByRole('button', { name: '隐藏' })[0])
    await waitFor(() => expect(hideSpy).toHaveBeenCalledWith(1))
  })

  it('删除自己的评论失败时回滚并提示', async () => {
    const { api } = await import('../api/client')
    vi.spyOn(api, 'comments').mockResolvedValue(FIXTURE)
    vi.spyOn(api, 'deleteComment').mockRejectedValue(new Error('boom'))
    render(<CommentSection repoId={1} canModerate={false} onNeedLogin={() => {}} />)
    await screen.findByText('审核中内容')
    await userEvent.click(screen.getAllByRole('button', { name: '删除' })[0])
    expect(await screen.findByText('操作失败，请重试')).toBeInTheDocument()
    expect(screen.getByText('审核中内容')).toBeInTheDocument()
  })
})
