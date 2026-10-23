// src/pages/HomePage.test.tsx
import { act, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { FIXTURE_REPOS } from '../api/fixtures'
import { useFeedStore } from '../store/feedStore'
import { mockIntersectionObserver } from '../test/mockIntersectionObserver'
import HomePage from './HomePage'

function renderPage(initialUrl = '/') {
  return render(<HomePage />, {
    wrapper: ({ children }) => (
      <MemoryRouter initialEntries={[initialUrl]}>{children}</MemoryRouter>
    ),
  })
}

describe('HomePage', () => {
  beforeEach(() => {
    useFeedStore.setState({
      cards: [], total: 0, loading: false, error: null, hasMore: true,
      page: 0, category: null, filters: {}, filterKey: '',
    })
  })

  it('渲染卡片流', async () => {
    render(<HomePage />, { wrapper: MemoryRouter })
    // 无封面卡：仓库名只出现在标题链接中
    expect(await screen.findAllByText('mini-agent')).not.toHaveLength(0)
    expect(screen.getAllByText('tinyfetch')).not.toHaveLength(0)
  })

  it('不再渲染「今日精选」区块', async () => {
    render(<HomePage />, { wrapper: MemoryRouter })
    await screen.findAllByText('mini-agent')
    expect(screen.queryByRole('region', { name: '今日精选' })).not.toBeInTheDocument()
  })

  it('哨兵进视口触发翻页', async () => {
    const io = mockIntersectionObserver()
    render(<HomePage />, { wrapper: MemoryRouter })
    await screen.findAllByText('mini-agent')
    expect(useFeedStore.getState().cards).toHaveLength(8)
    await act(async () => io.triggerEnter()) // act 包裹，避免外部状态更新警告
    await screen.findAllByText('wasm-notes')
    expect(useFeedStore.getState().cards).toHaveLength(12)
  })

  it('空分类显示空态与推广按钮', async () => {
    useFeedStore.setState({ cards: [], loading: false, hasMore: false, page: 1, category: '其他' })
    render(<HomePage />, {
      wrapper: ({ children }) => (
        <MemoryRouter initialEntries={['/?cat=其他']}>{children}</MemoryRouter>
      ),
    })
    expect(await screen.findByText('这个分类还没有仓库')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: '推广我的仓库' })).toBeInTheDocument()
  })

  it('深链带分类参数时按分类加载', async () => {
    render(<HomePage />, {
      wrapper: ({ children }) => (
        <MemoryRouter initialEntries={['/?cat=AI 与机器学习']}>{children}</MemoryRouter>
      ),
    })
    expect(await screen.findByText('llm-eval-kit')).toBeInTheDocument()
    expect(useFeedStore.getState().category).toBe('AI 与机器学习')
  })

  it('错误态显示重试', async () => {
    useFeedStore.setState({ cards: [], loading: false, error: '网络开小差了', hasMore: false, page: 1, category: null })
    render(<HomePage />, { wrapper: MemoryRouter })
    expect(await screen.findByText('加载失败，请重试')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: '重试' })).toBeInTheDocument()
  })

  it('页面提供 h1 标题', async () => {
    render(<HomePage />, { wrapper: MemoryRouter })
    await screen.findAllByText('mini-agent')
    expect(screen.getByRole('heading', { level: 1 })).toHaveTextContent('觅码')
  })

  it('翻页失败时错误条仍可见（已有卡片）', async () => {
    useFeedStore.setState({
      cards: [FIXTURE_REPOS[0]], loading: false, error: '某错误',
      hasMore: false, page: 1, category: null,
    })
    render(<HomePage />, { wrapper: MemoryRouter })
    expect(await screen.findByText('加载失败，请重试')).toBeInTheDocument()
  })

  it('过滤参数进 URL 时带 filters 请求，并渲染已选条件行', async () => {
    const { api } = await import('../api/client')
    const spy = vi.spyOn(api, 'feed').mockResolvedValue({ cards: [], has_more: false, total: 0 })
    renderPage('/?cat=开发工具&lang=Python&stars=100')
    await waitFor(() => expect(spy).toHaveBeenCalled())
    expect(spy).toHaveBeenCalledWith('开发工具', 1, expect.objectContaining({ lang: 'Python', stars: 100 }))
    expect(await screen.findByText('清除全部')).toBeInTheDocument()
    spy.mockRestore()
  })

  it('过滤后空态给「清除筛选」而非推广入口', async () => {
    const { api } = await import('../api/client')
    vi.spyOn(api, 'feed').mockResolvedValue({ cards: [], has_more: false, total: 0 })
    renderPage('/?lang=Zig')
    const clear = await screen.findByRole('button', { name: '清除筛选' })
    expect(screen.queryByRole('button', { name: '推广我的仓库' })).not.toBeInTheDocument()
    await userEvent.click(clear)
    // 清除后 filters 归零、回常规空态（store.filterKey 是 URL 过滤状态的镜像）
    await waitFor(() => expect(useFeedStore.getState().filterKey).toBe(''))
    expect(await screen.findByRole('button', { name: '推广我的仓库' })).toBeInTheDocument()
  })
})
