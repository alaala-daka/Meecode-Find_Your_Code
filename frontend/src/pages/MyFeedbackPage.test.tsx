// src/pages/MyFeedbackPage.test.tsx —— 我的反馈列表
import { fireEvent, render, screen } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { afterEach, describe, expect, it, vi } from 'vitest'

import type { MyFeedbackPage as MyFeedbackPageDto } from '../api/types'
import { MyFeedbackPage } from './MyFeedbackPage'

// 类型标注防字面量拓宽（category/status 联合类型；tsc --noEmit 覆盖测试文件）
const PAGE: MyFeedbackPageDto = {
  items: [
    { id: 2, category: 'suggest', body_preview: '希望支持按更新时间排序', status: 'pending',
      created_at: 1_700_000_000, updated_at: 1_700_000_000,
      last_reply_preview: '已记下，排期评估', last_reply_at: 1_700_100_000, unread_count: 1 },
    { id: 1, category: 'bug', body_preview: '窄屏文件树错乱', status: 'done',
      created_at: 1_699_000_000, updated_at: 1_699_500_000,
      last_reply_preview: null, last_reply_at: null, unread_count: 0 },
  ],
  total: 2,
}

const renderAt = (url = '/my/feedback') =>
  render(
    <MemoryRouter initialEntries={[url]}>
      <Routes>
        <Route path="/my/feedback" element={<MyFeedbackPage />} />
        <Route path="/my/feedback/:id" element={<p>详情页</p>} />
      </Routes>
    </MemoryRouter>,
  )

afterEach(() => vi.restoreAllMocks())

describe('MyFeedbackPage', () => {
  it('渲染行与状态徽标', async () => {
    const { api } = await import('../api/client')
    vi.spyOn(api, 'myFeedback').mockResolvedValue(PAGE)
    renderAt()
    expect(await screen.findByText('希望支持按更新时间排序')).toBeInTheDocument()
    expect(screen.getByText('待处理')).toBeInTheDocument()
    expect(screen.getByText('已处理')).toBeInTheDocument()
    expect(screen.getByText('1 条未读回复')).toBeInTheDocument()
  })

  it('行点击进详情', async () => {
    const { api } = await import('../api/client')
    vi.spyOn(api, 'myFeedback').mockResolvedValue(PAGE)
    renderAt()
    fireEvent.click(await screen.findByRole('link', { name: /希望支持按更新时间排序/ }))
    expect(await screen.findByText('详情页')).toBeInTheDocument()
  })

  it('空态', async () => {
    const { api } = await import('../api/client')
    vi.spyOn(api, 'myFeedback').mockResolvedValue({ items: [], total: 0 })
    renderAt()
    expect(await screen.findByText('还没有提交过反馈')).toBeInTheDocument()
  })

  it('错误态', async () => {
    const { api } = await import('../api/client')
    vi.spyOn(api, 'myFeedback').mockRejectedValue(new Error('加载失败'))
    renderAt()
    expect(await screen.findByRole('alert')).toBeInTheDocument()
  })
})
