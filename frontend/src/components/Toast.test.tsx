import { act, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import Toast from './Toast'

describe('Toast', () => {
  afterEach(() => vi.useRealTimers())
  it('message 非空渲染，4s 自动 onDismiss；为空不渲染', () => {
    vi.useFakeTimers()
    const onDismiss = vi.fn()
    const { rerender, container } = render(<Toast message="仓库消失了" onDismiss={onDismiss} />)
    expect(screen.getByRole('status')).toHaveTextContent('仓库消失了')
    act(() => { vi.advanceTimersByTime(4000) })
    expect(onDismiss).toHaveBeenCalled()
    rerender(<Toast message={null} onDismiss={onDismiss} />)
    expect(container.firstChild).toBeNull()
  })
})
