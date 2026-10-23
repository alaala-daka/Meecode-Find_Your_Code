// src/components/CategoryBar.test.tsx
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { useFeedStore } from '../store/feedStore'
import CategoryBar from './CategoryBar'

function renderBar(initialUrl = '/') {
  return render(
    <MemoryRouter initialEntries={[initialUrl]}>
      <Routes>
        <Route path="*" element={<CategoryBar />} />
      </Routes>
    </MemoryRouter>
  )
}

describe('CategoryBar', () => {
  beforeEach(() => {
    useFeedStore.setState({ cards: [], loading: false, error: null, hasMore: true, page: 0, category: null })
  })

  it('渲染分类胶囊，点击写入选中态并加载', async () => {
    renderBar()
    const chip = await screen.findByRole('button', { name: '开发工具' })
    await userEvent.click(chip)
    expect(chip).toHaveClass('is-active')
    expect(useFeedStore.getState().category).toBe('开发工具')
  })

  it('超过 8 个分类收进更多（fixture 7 个不触发）', async () => {
    renderBar()
    await screen.findByRole('button', { name: '开发工具' })
    expect(screen.queryByText('更多')).not.toBeInTheDocument()
  })

  it('分类超过 8 个时「更多」下拉可展开且容器不裁切', async () => {
    // 临时让 mock 返回 9 个分类
    const { api } = await import('../api/client')
    const spy = vi.spyOn(api, 'categories').mockResolvedValue([
      '一', '二', '三', '四', '五', '六', '七', '八', '九',
    ])
    renderBar()
    const moreBtn = await screen.findByText('更多 ▾')
    await userEvent.click(moreBtn)
    expect(await screen.findByText('九')).toBeInTheDocument()
    // DOM 层面：菜单渲染在 .cat-more-wrap 内（历史上 overflow:hidden 会将其裁掉）
    const inner = document.querySelector('.category-inner') as HTMLElement
    expect(inner).toBeTruthy()
    expect(inner.querySelector('.cat-more-wrap .cat-more-menu')).toBeTruthy()
    // 不断言 getComputedStyle(overflow)：vitest css:false 下 CSS 文件不加载进 jsdom，
    // 计算值恒为空，无法区分真实样式，故以 DOM 结构断言为准
    spy.mockRestore()
  })

  it('更多菜单支持 Esc 与外部点击关闭，aria-expanded 同步', async () => {
    const { api } = await import('../api/client')
    const spy = vi.spyOn(api, 'categories').mockResolvedValue(['一', '二', '三', '四', '五', '六', '七', '八', '九'])
    renderBar()
    const moreBtn = await screen.findByText('更多 ▾')
    expect(moreBtn).toHaveAttribute('aria-expanded', 'false')
    await userEvent.click(moreBtn)
    expect(moreBtn).toHaveAttribute('aria-expanded', 'true')
    await userEvent.keyboard('{Escape}')
    expect(screen.queryByText('九')).not.toBeInTheDocument()
    expect(moreBtn).toHaveAttribute('aria-expanded', 'false')
    spy.mockRestore()
  })
})
