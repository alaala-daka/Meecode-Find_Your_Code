// src/components/CommentSection.test.tsx
import { render, screen, waitFor, act } from '@testing-library/react'
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
      parent_id: null, content: '一楼', status: 'visible' as const, moderation_reason: '',
      created_at: 1, created_at_iso: '2026-01-01T00:00:00+00:00',
    },
    {
      id: 2, repo_id: 1, user_id: 3, user_login: 'bob', user_avatar: '',
      parent_id: 1, content: '回复一楼', status: 'visible' as const, moderation_reason: '',
      created_at: 2, created_at_iso: '2026-01-01T00:01:00+00:00',
    },
    {
      id: 3, repo_id: 1, user_id: 9, user_login: 'me', user_avatar: '',
      parent_id: null, content: '审核中内容', status: 'pending' as const, moderation_reason: '',
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

  it('hidden 带判定原因显示「未通过审核」，无原因显示「已隐藏」', async () => {
    const { api } = await import('../api/client')
    vi.spyOn(api, 'comments').mockResolvedValue({
      items: [
        {
          id: 1, repo_id: 1, user_id: 2, user_login: 'a', user_avatar: '', parent_id: null,
          content: '被判', status: 'hidden', created_at: 1, created_at_iso: '2026-01-01T00:00:00+00:00',
          moderation_reason: '命中广告',
        },
        {
          id: 2, repo_id: 1, user_id: 2, user_login: 'a', user_avatar: '', parent_id: null,
          content: '被作者隐', status: 'hidden', created_at: 2, created_at_iso: '2026-01-01T00:01:00+00:00',
          moderation_reason: '',
        },
      ],
      total: 2,
    })
    render(<CommentSection repoId={1} canModerate={false} onNeedLogin={() => {}} />)
    expect(await screen.findByText('未通过审核')).toBeInTheDocument()
    expect(screen.getByText('已隐藏')).toBeInTheDocument()
    expect(screen.getByText('未通过审核')).toHaveAttribute('title', '命中广告')
  })

  it('hidden 评论不显示「回复」按钮（作者本人也不可回复）', async () => {
    const { api } = await import('../api/client')
    vi.spyOn(api, 'comments').mockResolvedValue({
      items: [
        {
          id: 1, repo_id: 1, user_id: 9, user_login: 'me', user_avatar: '', parent_id: null,
          content: '被隐', status: 'hidden', created_at: 1, created_at_iso: '2026-01-01T00:00:00+00:00',
          moderation_reason: '',
        },
        {
          id: 2, repo_id: 1, user_id: 9, user_login: 'me', user_avatar: '', parent_id: null,
          content: '正常', status: 'visible', created_at: 2, created_at_iso: '2026-01-01T00:01:00+00:00',
          moderation_reason: '',
        },
      ],
      total: 2,
    })
    render(<CommentSection repoId={1} canModerate={false} onNeedLogin={() => {}} />)
    await screen.findByText('被隐')
    expect(screen.getAllByRole('button', { name: '回复' })).toHaveLength(1)   // 仅正常评论有
    expect(screen.getAllByRole('button', { name: '删除' })).toHaveLength(2)   // 删除不受限
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
      parent_id: null, content: '新评论', status: 'pending', moderation_reason: '',
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

  it('回复态未键入时占位显示「回复 @对象：」，对象为被点评论的作者', async () => {
    const { api } = await import('../api/client')
    vi.spyOn(api, 'comments').mockResolvedValue(FIXTURE)
    render(<CommentSection repoId={1} canModerate={false} onNeedLogin={() => {}} />)
    await screen.findByText('一楼')
    await userEvent.click(screen.getAllByRole('button', { name: '回复' })[1])
    expect(screen.getByRole('textbox')).toHaveAttribute('placeholder', '回复 @bob：')
  })

  it('点「回到上级评论」上箭头退出回复态，主表单恢复', async () => {
    const { api } = await import('../api/client')
    vi.spyOn(api, 'comments').mockResolvedValue(FIXTURE)
    render(<CommentSection repoId={1} canModerate={false} onNeedLogin={() => {}} />)
    await screen.findByText('一楼')
    await userEvent.click(screen.getAllByRole('button', { name: '回复' })[0])
    await userEvent.click(screen.getByRole('button', { name: '回到上级评论' }))
    expect(screen.queryByRole('button', { name: '回到上级评论' })).not.toBeInTheDocument()
    expect(screen.getByRole('textbox')).toHaveAttribute('placeholder', '写下你的评论…')
  })

  it('回复发送带顶层 parent_id', async () => {
    const { api } = await import('../api/client')
    vi.spyOn(api, 'comments').mockResolvedValue(FIXTURE)
    const postSpy = vi.spyOn(api, 'postComment').mockResolvedValue({
      id: 99, repo_id: 1, user_id: 9, user_login: 'me', user_avatar: '',
      parent_id: 1, content: '回你', status: 'pending', moderation_reason: '',
      created_at: 9, created_at_iso: 'x',
    })
    render(<CommentSection repoId={1} canModerate={false} onNeedLogin={() => {}} />)
    await screen.findByText('一楼')
    await userEvent.click(screen.getAllByRole('button', { name: '回复' })[1])   // bob 的回复
    await userEvent.type(screen.getByRole('textbox'), '回你')
    await userEvent.click(screen.getByRole('button', { name: '发送' }))
    await waitFor(() => expect(postSpy).toHaveBeenCalledWith(1, '回你', 1))
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

  it('含审核中评论时轮询刷新，状态即时更新且定格后停止', async () => {
    const { api } = await import('../api/client')
    const spy = vi.spyOn(api, 'comments')
      .mockResolvedValueOnce({ items: [FIXTURE.items[2]], total: 1 })
      .mockResolvedValue({ items: [{ ...FIXTURE.items[2], status: 'visible' as const }], total: 1 })
    vi.useFakeTimers()
    try {
      render(<CommentSection repoId={1} canModerate={false} onNeedLogin={() => {}} />)
      await act(async () => { await vi.advanceTimersByTimeAsync(0) })
      expect(screen.getByText('审核中')).toBeInTheDocument()
      expect(spy).toHaveBeenCalledTimes(1)
      await act(async () => { await vi.advanceTimersByTimeAsync(3000) })
      expect(spy).toHaveBeenCalledTimes(2)
      expect(screen.queryByText('审核中')).not.toBeInTheDocument()
      expect(screen.getByText('审核中内容')).toBeInTheDocument()
      await act(async () => { await vi.advanceTimersByTimeAsync(20000) })
      expect(spy).toHaveBeenCalledTimes(2)
    } finally {
      vi.useRealTimers()
    }
  })

  it('无 pending 评论时不发起轮询', async () => {
    const { api } = await import('../api/client')
    const spy = vi.spyOn(api, 'comments')
      .mockResolvedValue({ items: [FIXTURE.items[0], FIXTURE.items[1]], total: 2 })
    vi.useFakeTimers()
    try {
      render(<CommentSection repoId={1} canModerate={false} onNeedLogin={() => {}} />)
      await act(async () => { await vi.advanceTimersByTimeAsync(15000) })
      expect(spy).toHaveBeenCalledTimes(1)
    } finally {
      vi.useRealTimers()
    }
  })

  it('轮询失败静默：保留原列表不报错，恢复后继续', async () => {
    const { api } = await import('../api/client')
    vi.spyOn(api, 'comments')
      .mockResolvedValueOnce({ items: [FIXTURE.items[2]], total: 1 })
      .mockRejectedValueOnce(new Error('net'))
      .mockResolvedValue({ items: [{ ...FIXTURE.items[2], status: 'visible' as const }], total: 1 })
    vi.useFakeTimers()
    try {
      render(<CommentSection repoId={1} canModerate={false} onNeedLogin={() => {}} />)
      await act(async () => { await vi.advanceTimersByTimeAsync(0) })
      await act(async () => { await vi.advanceTimersByTimeAsync(3000) })
      expect(screen.getByText('审核中')).toBeInTheDocument()
      expect(screen.queryByText('评论加载失败')).not.toBeInTheDocument()
      await act(async () => { await vi.advanceTimersByTimeAsync(3000) })
      expect(screen.queryByText('审核中')).not.toBeInTheDocument()
    } finally {
      vi.useRealTimers()
    }
  })
})
