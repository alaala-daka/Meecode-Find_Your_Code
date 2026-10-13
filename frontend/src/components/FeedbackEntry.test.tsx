// src/components/FeedbackEntry.test.tsx —— 反馈入口：登录守卫
import { fireEvent, render, screen } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { FeedbackEntry } from './FeedbackEntry'
import { useAuthStore } from '../store/authStore'

beforeEach(() => useAuthStore.setState({ user: null }))
afterEach(() => vi.restoreAllMocks())

describe('FeedbackEntry', () => {
  it('未登录点击弹登录框', () => {
    render(<FeedbackEntry variant="icon" />)
    fireEvent.click(screen.getByRole('button', { name: '反馈' }))
    expect(screen.getByRole('dialog', { name: '登录' })).toBeInTheDocument()
  })

  it('已登录点击开反馈表单', () => {
    useAuthStore.setState({ user: { id: 1, login: 'me', avatar_url: '', bio: '',
      gh_star_authed: false } })
    render(<FeedbackEntry variant="icon" />)
    fireEvent.click(screen.getByRole('button', { name: '反馈' }))
    expect(screen.getByRole('dialog', { name: '提交反馈' })).toBeInTheDocument()
  })

  it('text 变体渲染页脚文字链', () => {
    render(<FeedbackEntry variant="text" />)
    expect(screen.getByRole('button', { name: '反馈' })).toHaveClass('footer-cta')
  })
})
