// src/explain/ExplainPanel.test.tsx
import { act, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { RepoDetail } from '../api/types'
import ExplainPanel from './ExplainPanel'
import { useGraphStore } from './store/graphStore'
import { useReaderStore } from './store/readerStore'

vi.mock('./api/client', () => ({
  api: {
    createSession: vi.fn().mockResolvedValue({ session_id: 'sid-1' }),
    repoRoot: vi.fn().mockResolvedValue({
      node: { id: 'root', title: '根主题', content: '', node_type: 'concept', relevance: 1 },
      children: [],
      edges: [],
    }),
  },
  ApiError: class ApiError extends Error {
    constructor(public status: number, message: string) {
      super(message)
    }
  },
}))

// d3 模拟/缩放细节与本断言无关，替换为占位
vi.mock('./components/GraphCanvas', () => ({
  GraphCanvas: () => <div className="graph-canvas" />,
}))

const REPO = {
  github_url: 'https://github.com/alice/mini-agent',
  default_branch: 'main',
} as RepoDetail

const META = { nodeId: 'n1', title: '历史背景', path: ['根主题', '历史背景'] }

/** jsdom 无真实媒体查询，按 useIsMobile 约定桩出视口（同 TopBar.test.tsx:122 的形状） */
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

/** 渲染并等 build() 完成（setRoot 后 rootId 就位，之后再动 readerStore 才不会被 build 的 reset 冲掉） */
async function renderPanel() {
  const view = render(<ExplainPanel repo={REPO} />)
  await waitFor(() => expect(useGraphStore.getState().rootId).toBe('root'))
  return view
}

describe('ExplainPanel 移动端阅读态（≤720px）', () => {
  beforeEach(() => {
    stubViewport(true)
    useReaderStore.getState().reset()
  })
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('阅读器关闭时根节点无 explain-root--reading', async () => {
    const { container } = await renderPanel()
    expect(container.querySelector('.explain-root')).not.toHaveClass('explain-root--reading')
  })

  it('展开解读后进入阅读态（整屏切换，非抽屉）', async () => {
    const { container } = await renderPanel()
    act(() => useReaderStore.getState().openWith(META, '精读正文'))
    expect(container.querySelector('.explain-root')).toHaveClass('explain-root--reading')
    expect(screen.getByRole('complementary', { name: '概念精读阅读器' })).toBeInTheDocument()
  })
})

describe('ExplainPanel 桌面端（>720px）', () => {
  beforeEach(() => {
    stubViewport(false)
    useReaderStore.getState().reset()
  })
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('打开阅读器也不加阅读态类（桌面布局不变）', async () => {
    const { container } = await renderPanel()
    act(() => useReaderStore.getState().openWith(META, '精读正文'))
    expect(container.querySelector('.explain-root')).not.toHaveClass('explain-root--reading')
  })
})
