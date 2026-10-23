// src/components/FilterChips.test.tsx
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Route, Routes, useLocation } from 'react-router-dom'
import { describe, expect, it } from 'vitest'
import FilterChips from './FilterChips'

function LocationProbe() {
  return <span data-testid="url">{useLocation().search}</span>
}

function renderChips(initialUrl: string, total?: number) {
  return render(
    <MemoryRouter initialEntries={[initialUrl]}>
      <Routes>
        <Route path="*" element={<><FilterChips total={total} /><LocationProbe /></>} />
      </Routes>
    </MemoryRouter>
  )
}

describe('FilterChips', () => {
  it('无筛选时渲染 null', () => {
    renderChips('/')
    expect(screen.queryByText('清除全部')).not.toBeInTheDocument()
  })

  it('渲染已选条件、计数与可访问名称', () => {
    renderChips('/?lang=Python&stars=100&topic=llm', 128)
    expect(screen.getByText('Python')).toBeInTheDocument()
    expect(screen.getByText('★ ≥ 100')).toBeInTheDocument()
    expect(screen.getByText('#llm')).toBeInTheDocument()
    expect(screen.getByText('共 128 个仓库')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: '移除语言筛选 Python' })).toBeInTheDocument()
  })

  it('点单条 ✕ 移除该条件并重置 page，其他参数保留', async () => {
    renderChips('/?q=abc&lang=Python&stars=100&page=3')
    await userEvent.click(screen.getByRole('button', { name: '移除语言筛选 Python' }))
    const url = screen.getByTestId('url').textContent ?? ''
    expect(url).not.toContain('lang=')
    expect(url).toContain('stars=100')
    expect(url).toContain('q=abc')
    expect(url).not.toContain('page=')
  })

  it('清除全部只清白名单参数', async () => {
    renderChips('/?cat=开发工具&lang=Go&since=7d&topic=llm')
    await userEvent.click(screen.getByText('清除全部'))
    const url = screen.getByTestId('url').textContent ?? ''
    expect(url).toContain('cat=')
    expect(url).not.toContain('lang=')
    expect(url).not.toContain('since=')
    expect(url).not.toContain('topic=')
  })

  it('条件行类名归 FilterChips 自有（filter-chips / filter-chip + is-active）', () => {
    renderChips('/?lang=Python')
    const row = screen.getByRole('group', { name: '已选筛选条件' })
    expect(row).toHaveClass('filter-chips')
    const chip = screen.getByRole('button', { name: '移除语言筛选 Python' })
    expect(chip).toHaveClass('filter-chip', 'is-active')
    expect(row.querySelector('.filter-panel-chip')).toBeNull()   // 面板专用前缀不混入
  })
})

describe('FilterChips / FilterPanel 样式作用域隔离', () => {
  // 注释里的示例类名不构成选择器：先剥注释再解析
  const strip = (css: string) => css.replace(/\/\*[\s\S]*?\*\//g, '')
  const chipsCss = strip(readFileSync(resolve(__dirname, 'FilterChips.css'), 'utf-8'))
  const panelCss = strip(readFileSync(resolve(__dirname, 'FilterPanel.css'), 'utf-8'))

  function classSelectors(css: string): Set<string> {
    // 只比组件自有前缀 filter-*；is-active 等共享状态类不算作用域泄漏
    return new Set([...css.matchAll(/\.(filter-[\w-]+)/g)].map((m) => m[1]))
  }

  it('两个样式表类名零交集（同名不同值冲突已消除）', () => {
    const panel = classSelectors(panelCss)
    const shared = [...classSelectors(chipsCss)].filter((c) => panel.has(c))
    expect(shared).toEqual([])
  })

  it('FilterPanel.css 不再使用 .filter-chip / .filter-chips 短名', () => {
    // 「filter-panel-chip」不含子串「filter-chip」，可作精确短名探测
    expect(panelCss).not.toContain('filter-chip')
    expect(panelCss).not.toContain('filter-chips')
  })

  it('激活样式自持：FilterChips.css 自带 .filter-chip.is-active 规则', () => {
    expect(chipsCss).toContain('.filter-chip.is-active')
  })
})
