// src/components/FeedbackModal.test.tsx —— 反馈弹窗：焦点圈定/提交/校验
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { FeedbackModal } from './FeedbackModal'
import { useAuthStore } from '../store/authStore'

const USER = { id: 9, login: 'me', avatar_url: '', bio: '', gh_star_authed: false }

beforeEach(() => {
  useAuthStore.setState({ user: USER })
})

afterEach(() => vi.restoreAllMocks())

describe('FeedbackModal', () => {
  it('渲染三类胶囊与两个计数', () => {
    render(<FeedbackModal open onClose={() => {}} />)
    expect(screen.getByRole('dialog')).toBeInTheDocument()
    for (const label of ['问题反馈', '建议', '其他']) {
      expect(screen.getByRole('button', { name: label })).toBeInTheDocument()
    }
    expect(screen.getByText('0/500')).toBeInTheDocument()
    expect(screen.getByText('0/100')).toBeInTheDocument()
  })

  it('浮层 portal 到 body：不被顶栏 backdrop-filter 含块截留（回归）', () => {
    render(
      <div data-testid="host" style={{ backdropFilter: 'blur(8px)' }}>
        <FeedbackModal open onClose={() => {}} />
      </div>,
    )
    // 不 portal 时 .fb-mask 会落在顶栏子树内，fixed 的 inset:0 只铺满顶栏条，弹窗被顶出屏幕
    expect(screen.getByRole('dialog').closest('[data-testid="host"]')).toBeNull()
  })

  it('提交成功回调并关闭', async () => {
    const { api } = await import('../api/client')
    vi.spyOn(api, 'submitFeedback').mockResolvedValue({ id: 3 })
    const onSubmitted = vi.fn()
    const onClose = vi.fn()
    render(<FeedbackModal open onClose={onClose} onSubmitted={onSubmitted} />)
    // label 内嵌 0/500 计数器，label 文本是「反馈内容0/500」→ 用正则匹配
    fireEvent.change(screen.getByLabelText(/反馈内容/), { target: { value: '页面崩了' } })
    fireEvent.click(screen.getByRole('button', { name: '提交反馈' }))
    await waitFor(() => expect(onSubmitted).toHaveBeenCalled())
    expect(onClose).toHaveBeenCalled()
  })

  it('空白正文不发请求并内联报错', async () => {
    const { api } = await import('../api/client')
    const spy = vi.spyOn(api, 'submitFeedback')
    render(<FeedbackModal open onClose={() => {}} />)
    fireEvent.click(screen.getByRole('button', { name: '提交反馈' }))
    expect(await screen.findByRole('alert')).toBeInTheDocument()
    expect(spy).not.toHaveBeenCalled()
  })

  it('未登录时弹登录框而非反馈表单', () => {
    useAuthStore.setState({ user: null })
    render(<FeedbackModal open onClose={() => {}} />)
    expect(screen.getByRole('dialog', { name: '登录' })).toBeInTheDocument()
  })
})
