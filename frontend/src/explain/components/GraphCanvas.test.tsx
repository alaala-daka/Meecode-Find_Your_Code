// src/explain/components/GraphCanvas.test.tsx
import { act, render } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { NodePayload } from '../api/client'
import { useGraphStore } from '../store/graphStore'
import { useReaderStore } from '../store/readerStore'
import { GraphCanvas } from './GraphCanvas'

vi.mock('../api/client', () => ({
  api: { chatStream: vi.fn() },
  ApiError: class ApiError extends Error {
    constructor(public status: number, message: string) {
      super(message)
    }
  },
}))

// 缩放适配的动画出口打桩，断言"是否触发重排"
vi.mock('../graph/zoomFit', () => ({
  animateZoomTo: vi.fn(() => () => {}),
  clampWorldToViewport: vi.fn((x: number, y: number) => ({ x, y })),
  ensureVisibleTransform: vi.fn((_b, _w, _h, current) => current),
  fitTransform: vi.fn(() => ({ x: 0, y: 0, k: 1 })),
  graphBBox: vi.fn(() => ({ x: 0, y: 0, width: 100, height: 100 })),
}))

const { animateZoomTo } = await import('../graph/zoomFit')

const NODE: NodePayload = { id: 'root', title: '根主题', content: '', node_type: 'concept', relevance: 1 }
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

function mountCanvas() {
  const view = render(<GraphCanvas />)
  expect(animateZoomTo).toHaveBeenCalled() // 挂载时首次入图 fit
  vi.mocked(animateZoomTo).mockClear()
  return view
}

describe('GraphCanvas 移动端阅读态（≤720px）', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    stubViewport(true)
    useGraphStore.getState().reset()
    useReaderStore.getState().reset()
    useGraphStore.getState().setRoot(NODE)
  })
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('进入阅读态不触发重排；退出时全幅归位', () => {
    mountCanvas()
    act(() => useReaderStore.getState().openWith(META, '精读正文'))
    expect(animateZoomTo).not.toHaveBeenCalled()
    act(() => useReaderStore.getState().close())
    expect(animateZoomTo).toHaveBeenCalled()
  })
})

describe('GraphCanvas 桌面端（>720px）回归', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    stubViewport(false)
    useGraphStore.getState().reset()
    useReaderStore.getState().reset()
    useGraphStore.getState().setRoot(NODE)
  })
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('打开阅读器仍做挤缩适配（原行为不变）', () => {
    mountCanvas()
    act(() => useReaderStore.getState().openWith(META, '精读正文'))
    expect(animateZoomTo).toHaveBeenCalled()
  })
})
