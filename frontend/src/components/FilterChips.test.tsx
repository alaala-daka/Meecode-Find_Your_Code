// src/components/FilterChips.test.tsx
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
})
