// src/components/FilterPanel.test.tsx
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Route, Routes, useLocation } from 'react-router-dom'
import { afterEach, describe, expect, it, vi } from 'vitest'
import FilterPanel from './FilterPanel'

function LocationProbe() {
  return <span data-testid="url">{useLocation().search}</span>
}

function renderPanel(initialUrl = '/') {
  return render(
    <MemoryRouter initialEntries={[initialUrl]}>
      <Routes>
        <Route path="*" element={<><FilterPanel /><LocationProbe /></>} />
      </Routes>
    </MemoryRouter>
  )
}

function mockMatchMedia(matches: boolean) {
  vi.stubGlobal('matchMedia', vi.fn().mockImplementation((q: string) => ({
    matches, media: q,
    addEventListener: vi.fn(), removeEventListener: vi.fn(),
    addListener: vi.fn(), removeListener: vi.fn(),
  })))
}

afterEach(() => vi.unstubAllGlobals())

describe('FilterPanel', () => {
  it('触发器展开面板，aria-expanded 同步', async () => {
    renderPanel()
    const trigger = screen.getByRole('button', { name: /筛选/ })
    expect(trigger).toHaveAttribute('aria-expanded', 'false')
    await userEvent.click(trigger)
    expect(trigger).toHaveAttribute('aria-expanded', 'true')
    expect(screen.getByRole('dialog', { name: '精确筛选' })).toBeInTheDocument()
  })

  it('草稿隔离：面板内点选不改 URL，应用后一次写入并关闭', async () => {
    renderPanel()
    await userEvent.click(screen.getByRole('button', { name: /筛选/ }))
    await userEvent.click(await screen.findByRole('button', { name: 'Python' }))
    expect(screen.getByTestId('url').textContent).not.toContain('lang=')   // 草稿期不动 URL
    await userEvent.click(screen.getByRole('button', { name: '应用筛选' }))
    const url = screen.getByTestId('url').textContent ?? ''
    expect(url).toContain('lang=Python')
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
  })

  it('取消 / Esc 还原草稿', async () => {
    renderPanel('/?lang=Go')
    await userEvent.click(screen.getByRole('button', { name: /筛选/ }))
    await userEvent.click(await screen.findByRole('button', { name: 'Python' }))  // 草稿改选
    await userEvent.keyboard('{Escape}')
    expect(screen.getByTestId('url').textContent).toContain('lang=Go')
    // 再开面板：草稿应为 URL 现值
    await userEvent.click(screen.getByRole('button', { name: /筛选/ }))
    expect(await screen.findByRole('button', { name: 'Go' })).toHaveClass('is-active')
  })

  it('应用筛选重置 page', async () => {
    renderPanel('/?q=abc&page=5')
    await userEvent.click(screen.getByRole('button', { name: /筛选/ }))
    await userEvent.click(screen.getByRole('button', { name: '近一月' }))
    await userEvent.click(screen.getByRole('button', { name: '应用筛选' }))
    const url = screen.getByTestId('url').textContent ?? ''
    expect(url).toContain('since=30d')
    expect(url).not.toContain('page=')
  })

  it('星数自定义区间走 stars / stars_max 两参数', async () => {
    renderPanel()
    await userEvent.click(screen.getByRole('button', { name: /筛选/ }))
    await userEvent.click(screen.getByRole('button', { name: '自定义…' }))
    await userEvent.type(screen.getByLabelText('最少星数'), '123')
    await userEvent.type(screen.getByLabelText('最多星数'), '456')
    await userEvent.click(screen.getByRole('button', { name: '应用筛选' }))
    const url = screen.getByTestId('url').textContent ?? ''
    expect(url).toContain('stars=123')
    expect(url).toContain('stars_max=456')
  })

  it('topics 多选上限 5 个', async () => {
    renderPanel()
    await userEvent.click(screen.getByRole('button', { name: /筛选/ }))
    // 夹具 topics 按计数排序后前 6 可见（chip 文案带 # 前缀）：6 选 → 上限 5
    for (const t of ['#llm', '#agent', '#runtime', '#http', '#fetch', '#kv']) {
      const chip = await screen.findByRole('button', { name: t })
      if (!chip.hasAttribute('disabled')) await userEvent.click(chip)
    }
    await userEvent.click(screen.getByRole('button', { name: '应用筛选' }))
    expect(screen.getByTestId('url').textContent.match(/topic=/g)?.length).toBe(5)
  })

  it('手机端渲染底部半屏与遮罩', async () => {
    mockMatchMedia(true)
    renderPanel()
    await userEvent.click(screen.getByRole('button', { name: /筛选/ }))
    const panel = screen.getByRole('dialog', { name: '精确筛选' })
    expect(panel).toHaveClass('filter-panel--sheet')
    expect(document.querySelector('.filter-mask')).toBeTruthy()
  })

  it('手机端点遮罩关闭面板', async () => {
    mockMatchMedia(true)
    renderPanel()
    await userEvent.click(screen.getByRole('button', { name: /筛选/ }))
    expect(screen.getByRole('dialog', { name: '精确筛选' })).toBeInTheDocument()
    await userEvent.click(document.querySelector('.filter-mask')!)
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
  })

  it('自定义星数区间从 URL 回显，round-trip 不丢', async () => {
    renderPanel('/?stars=123&stars_max=456')
    await userEvent.click(screen.getByRole('button', { name: /筛选/ }))
    expect(screen.getByRole('button', { name: '自定义…' })).toHaveClass('is-active')
    expect(screen.getByLabelText('最少星数')).toHaveValue('123')
    expect(screen.getByLabelText('最多星数')).toHaveValue('456')
    await userEvent.click(screen.getByRole('button', { name: '应用筛选' }))
    const url = screen.getByTestId('url').textContent ?? ''
    expect(url).toContain('stars=123')
    expect(url).toContain('stars_max=456')
  })

  it('面板 Portal 挂到 body（逃逸 .category-inner 的 overflow 裁剪链）', async () => {
    renderPanel()
    await userEvent.click(screen.getByRole('button', { name: /筛选/ }))
    const panel = screen.getByRole('dialog', { name: '精确筛选' })
    expect(panel.parentElement).toBe(document.body)
    expect(panel.closest('.filter-wrap')).toBeNull()   // 不再是触发器 wrap 的子节点
    // 桌面面板按触发器矩形注入 fixed 坐标（vitest css:false 不加载 CSS，断言行内坐标已写入）
    expect(panel.style.top).not.toBe('')
    expect(panel.style.right).not.toBe('')
  })

  it('面板内点击不算外部点击（草稿不丢），点面板外关闭', async () => {
    renderPanel()
    await userEvent.click(screen.getByRole('button', { name: /筛选/ }))
    // 面板内点选 chips：Portal 后不在 .filter-wrap 子树，仍须视为内部点击
    await userEvent.click(await screen.findByRole('button', { name: 'Python' }))
    expect(screen.getByRole('dialog', { name: '精确筛选' })).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: '应用筛选' }))
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
  })

  it('手机 sheet 与遮罩同样 Portal 到 body（fixed 不受祖先 overflow 影响）', async () => {
    mockMatchMedia(true)
    renderPanel()
    await userEvent.click(screen.getByRole('button', { name: /筛选/ }))
    const panel = screen.getByRole('dialog', { name: '精确筛选' })
    expect(panel.parentElement).toBe(document.body)
    const mask = document.querySelector('.filter-mask') as HTMLElement
    expect(mask.parentElement).toBe(document.body)
  })
})
