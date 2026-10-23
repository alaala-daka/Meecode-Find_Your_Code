// src/pages/SearchPage.test.tsx
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Route, Routes, useNavigate, useSearchParams } from 'react-router-dom'
import { describe, expect, it, vi } from 'vitest'
import SearchPage from './SearchPage'

function ParamProbe() {
  const [p] = useSearchParams()
  return <output data-testid="params">{p.toString()}</output>
}

function renderAt(url: string) {
  return render(
    <MemoryRouter initialEntries={[url]}>
      <Routes>
        <Route path="/search" element={<><SearchPage /><ParamProbe /></>} />
      </Routes>
    </MemoryRouter>
  )
}

function NavProbe() {
  const navigate = useNavigate()
  return <button onClick={() => navigate('/search?q=agent')}>换词探针</button>
}

function renderAtWithNav(url: string) {
  return render(
    <MemoryRouter initialEntries={[url]}>
      <Routes>
        <Route path="/search" element={<><SearchPage /><ParamProbe /></>} />
      </Routes>
      <NavProbe />
    </MemoryRouter>
  )
}

describe('SearchPage', () => {
  it('渲染横向富卡片：标题、卖点、作者、分类胶囊', async () => {
    renderAt('/search?q=agent')
    expect(await screen.findByTestId('search-card-1')).toBeInTheDocument()
    expect(screen.getByText('给 LLM Agent 的最小运行时，200 行可读完')).toBeInTheDocument()
    expect(screen.getByText('alice')).toBeInTheDocument()
    expect(screen.getByText('AI 与机器学习')).toBeInTheDocument()
  })

  it('命中词在标题中高亮', async () => {
    renderAt('/search?q=agent')
    const card = await screen.findByTestId('search-card-1')
    // 标题被 <mark> 拆分，无法按完整文本查询，直接在卡片内定位 mark
    const mark = card.querySelector('.search-title mark')
    expect(mark).toHaveTextContent('agent')
  })

  it('切换排序重新请求', async () => {
    renderAt('/search?q=a')
    await screen.findByTestId('search-card-1')
    await userEvent.click(screen.getByRole('tab', { name: '最多 star' }))
    const cards = await screen.findAllByTestId(/^search-card-/)
    expect(cards.length).toBeGreaterThan(0)
  })

  it('换关键词重置页码', async () => {
    // 'e' 命中 11 条（两页）：先翻到第 2 页，再改 q，页码必须回 1，否则第 2 页空白死页
    renderAtWithNav('/search?q=e')
    await screen.findAllByTestId(/^search-card-/)
    await userEvent.click(screen.getByRole('button', { name: '2' }))
    expect((await screen.findAllByTestId(/^search-card-/)).length).toBe(3)
    await userEvent.click(screen.getByRole('button', { name: '换词探针' }))
    expect(await screen.findByTestId('search-card-1')).toBeInTheDocument()
    expect(screen.getByText('搜索「agent」· 共 1 个结果')).toBeInTheDocument()
  })

  it('无结果显示空态', async () => {
    renderAt('/search?q=不存在的关键词')
    expect(await screen.findByText('没有找到相关仓库，换个关键词试试')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: '推广我的仓库' })).toBeInTheDocument()
  })

  it('排序与页码写入 URL', async () => {
    renderAt('/search?q=a')
    await screen.findByTestId('search-card-1')
    await userEvent.click(screen.getByRole('tab', { name: '最新' }))
    expect(await screen.findByTestId('params')).toHaveTextContent('sort=newest')
  })

  it('搜索失败显示错误条并可重试', async () => {
    const { api } = await import('../api/client')
    const spy = vi.spyOn(api, 'search').mockRejectedValueOnce(new Error('boom'))
    renderAt('/search?q=agent')
    expect(await screen.findByText('搜索失败，请重试')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: '重试' })).toBeInTheDocument()
    spy.mockRestore()
  })

  it('空关键词显示引导且不卡加载', async () => {
    renderAt('/search?q=')
    expect(await screen.findByText('在顶栏输入关键词开始搜索')).toBeInTheDocument()
    expect(screen.queryByText('搜索中…')).not.toBeInTheDocument()
  })
})
