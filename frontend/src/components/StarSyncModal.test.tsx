import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import StarSyncModal from './StarSyncModal'

describe('StarSyncModal', () => {
  it('双按钮与文案，点击分别回调', async () => {
    const onConfirmAuth = vi.fn(); const onLocalOnly = vi.fn(); const onClose = vi.fn()
    render(<StarSyncModal open onConfirmAuth={onConfirmAuth} onLocalOnly={onLocalOnly} onClose={onClose} />)
    expect(screen.getByText('取消收藏将同步取消 GitHub 星')).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: '授权并同步取消' }))
    await userEvent.click(screen.getByRole('button', { name: '仅取消本地收藏' }))
    expect(onConfirmAuth).toHaveBeenCalledTimes(1)
    expect(onLocalOnly).toHaveBeenCalledTimes(1)
  })

  it('Esc 与遮罩点击关闭', async () => {
    const onClose = vi.fn()
    render(<StarSyncModal open onConfirmAuth={vi.fn()} onLocalOnly={vi.fn()} onClose={onClose} />)
    await userEvent.keyboard('{Escape}')
    expect(onClose).toHaveBeenCalled()
    await userEvent.click(screen.getByRole('dialog').parentElement!)
    expect(onClose).toHaveBeenCalledTimes(2)
  })

  it('关闭态不渲染', () => {
    const { container } = render(
      <StarSyncModal open={false} onConfirmAuth={vi.fn()} onLocalOnly={vi.fn()} onClose={vi.fn()} />)
    expect(container.firstChild).toBeNull()
  })
})
