// src/explain/components/reader/ReaderPanel.test.tsx
import { act, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { useReaderStore } from '../../store/readerStore'
import { ReaderPanel } from './ReaderPanel'

const META = { nodeId: 'n1', title: '历史背景', path: ['根主题', '历史背景'] }

function stubViewport(mobile: boolean) {
  vi.stubGlobal('matchMedia', (query: string) => ({
    matches: mobile && query.includes('max-width: 720px'),
    media: query,
    onchange: null,
    addEventListener: () => {},
    removeEventListener: () => {},
    addListener: () => {},
    removeListener: () => {},
    dispatchEvent: () => false,
  }))
}

describe('ReaderPanel 移动端（≤720px）', () => {
  beforeEach(() => {
    stubViewport(true)
    act(() => useReaderStore.getState().reset())
    act(() => useReaderStore.getState().openWith(META, '精读正文'))
  })
  afterEach(() => {
    vi.unstubAllGlobals()
    act(() => useReaderStore.getState().reset())
  })

  it('关闭按钮语义为「返回概念图」，点击回到图', async () => {
    render(<ReaderPanel />)
    await userEvent.click(screen.getByRole('button', { name: '返回概念图' }))
    expect(useReaderStore.getState().open).toBe(false)
    expect(screen.queryByRole('complementary')).not.toBeInTheDocument()
  })
})

describe('ReaderPanel 桌面端（>720px）', () => {
  beforeEach(() => {
    stubViewport(false)
    act(() => useReaderStore.getState().reset())
    act(() => useReaderStore.getState().openWith(META, '精读正文'))
  })
  afterEach(() => {
    vi.unstubAllGlobals()
    act(() => useReaderStore.getState().reset())
  })

  it('关闭按钮仍为「收起阅读器」（桌面行为不变）', async () => {
    render(<ReaderPanel />)
    expect(screen.queryByRole('button', { name: '返回概念图' })).not.toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: '收起阅读器' }))
    expect(useReaderStore.getState().open).toBe(false)
  })
})
