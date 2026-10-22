// src/pages/SearchEntryPage.test.tsx
import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import SearchEntryPage from './SearchEntryPage'

const navigateSpy = vi.fn()
vi.mock('react-router-dom', async () => {
  const actual = await vi.importActual<typeof import('react-router-dom')>('react-router-dom')
  return { ...actual, useNavigate: () => navigateSpy }
})

function renderAt(...entries: string[]) {
  return render(
    <MemoryRouter initialEntries={entries}>
      <Routes>
        <Route path="/search-entry" element={<SearchEntryPage />} />
      </Routes>
    </MemoryRouter>
  )
}

// 本页内嵌 TopBar（桌面态另有同名「搜索」输入），查询限定在中间页主体内
function entryInput() {
  return within(screen.getByRole('main')).getByRole('textbox', { name: '搜索' })
}

describe('SearchEntryPage', () => {
  beforeEach(() => {
    navigateSpy.mockClear()
  })

  it('渲染全宽输入框并自动聚焦', () => {
    renderAt('/search-entry')
    expect(entryInput()).toHaveFocus()
  })

  it('输入关键词回车跳搜索结果页', async () => {
    renderAt('/search-entry')
    await userEvent.type(entryInput(), 'agent{Enter}')
    expect(navigateSpy).toHaveBeenCalledWith('/search?q=agent')
  })

  it('点「搜索」按钮同样跳搜索结果页', async () => {
    renderAt('/search-entry')
    await userEvent.type(entryInput(), 'latex')
    await userEvent.click(screen.getByRole('button', { name: '搜索' }))
    expect(navigateSpy).toHaveBeenCalledWith('/search?q=latex')
  })

  it('空输入或纯空格不跳转', async () => {
    renderAt('/search-entry')
    await userEvent.type(entryInput(), '   {Enter}')
    await userEvent.click(screen.getByRole('button', { name: '搜索' }))
    expect(navigateSpy).not.toHaveBeenCalled()
  })

  it('直达本页时取消回首页', async () => {
    renderAt('/search-entry')
    await userEvent.click(screen.getByRole('button', { name: '取消' }))
    expect(navigateSpy).toHaveBeenCalledWith('/')
  })

  it('站内跳入时取消回上一页', async () => {
    renderAt('/', '/search-entry')
    await userEvent.click(screen.getByRole('button', { name: '取消' }))
    expect(navigateSpy).toHaveBeenCalledWith(-1)
  })
})
