// src/pages/FeedbackDetailPage.test.tsx —— 我的反馈详情：进入即置已读 + 纯文本渲染
import { render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { afterEach, describe, expect, it, vi } from 'vitest'

import type { FeedbackDetail } from '../api/types'
import { FeedbackDetailPage } from './FeedbackDetailPage'
import { useNotificationStore } from '../store/notificationStore'

// 类型标注防字面量拓宽（category/status 联合类型；tsc --noEmit 覆盖测试文件）
const DETAIL: FeedbackDetail = {
  id: 1, category: 'bug', body: '详情正文 <script>x</script>',
  status: 'done', created_at: 1_700_000_000, updated_at: 1_700_500_000,
  replies: [{ id: 1, body: '已修复 **感谢**', author_login: 'meecode',
    created_at: 1_700_200_000 }],
}

const renderAt = () =>
  render(
    <MemoryRouter initialEntries={['/my/feedback/1']}>
      <Routes><Route path="/my/feedback/:id" element={<FeedbackDetailPage />} /></Routes>
    </MemoryRouter>,
  )

afterEach(() => vi.restoreAllMocks())

describe('FeedbackDetailPage', () => {
  it('渲染原文与回复串且内容按纯文本', async () => {
    const { api } = await import('../api/client')
    vi.spyOn(api, 'feedback').mockResolvedValue(DETAIL)
    renderAt()
    expect(await screen.findByText('详情正文 <script>x</script>')).toBeInTheDocument()
    expect(screen.getByText('已修复 **感谢**')).toBeInTheDocument()
    expect(screen.getByText('meecode')).toBeInTheDocument()
  })

  it('进入即刷新未读数', async () => {
    const { api } = await import('../api/client')
    vi.spyOn(api, 'feedback').mockResolvedValue(DETAIL)
    const refresh = vi.fn()
    useNotificationStore.setState({ count: 3, refresh })
    renderAt()
    await waitFor(() => expect(refresh).toHaveBeenCalled())
  })

  it('404 展示错误横幅', async () => {
    const { api } = await import('../api/client')
    vi.spyOn(api, 'feedback').mockRejectedValue(new Error('反馈不存在'))
    renderAt()
    expect(await screen.findByRole('alert')).toBeInTheDocument()
  })
})
