// src/components/CategoryBar.test.tsx
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
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

  it('行尾渲染筛选触发器，有生效条件时带徽标', async () => {
    renderBar('/?lang=Python&stars=100')
    // /^筛选/ 锚定触发器名开头：条件 chip 的可及名以「移除」开头，/筛选/ 会命中多个
    const trigger = await screen.findByRole('button', { name: /^筛选/ })
    expect(trigger).toHaveTextContent('2')
  })

  it('筛选面板 Portal 出 .category-inner 滚动容器（逃逸 overflow 裁剪）', async () => {
    renderBar()
    const trigger = await screen.findByRole('button', { name: /^筛选/ })
    await userEvent.click(trigger)
    const panel = screen.getByRole('dialog', { name: '精确筛选' })
    const inner = document.querySelector('.category-inner') as HTMLElement
    expect(inner).toBeTruthy()
    // 面板及其祖先链都不在横滚容器（overflow-x:auto → overflow-y 计算为 auto）内
    expect(inner.contains(panel)).toBe(false)
    expect(panel.closest('.category-inner')).toBeNull()
    // Portal 直接挂到 body：overflow 裁剪只作用于滚动容器盒子树的后代，够不到 body 子节点
    expect(panel.parentElement).toBe(document.body)
    // 触发器仍在滚动容器的 .filter-wrap 内（sticky 右锚定，窄桌面横滚时可达）
    expect(inner.querySelector('.filter-wrap')?.contains(trigger)).toBe(true)
  })

  it('条件行为 .category-bar 直接子级、与胶囊行同级（手机断点 display:contents 作用对象）', async () => {
    renderBar('/?lang=Python')
    const row = screen.getByRole('group', { name: '已选筛选条件' })
    expect(row.parentElement).toHaveClass('category-bar')
    expect(row.previousElementSibling).toHaveClass('category-inner')
    expect(row).toHaveClass('filter-chips')
  })
})

/** 取出某条 @media 规则的完整块文本（花括号配对） */
function mediaBlock(css: string, query: string): string {
  const start = css.indexOf(`@media (${query})`)
  expect(start).toBeGreaterThanOrEqual(0)
  const open = css.indexOf('{', start)
  let depth = 1
  let i = open + 1
  while (depth > 0 && i < css.length) {
    if (css[i] === '{') depth += 1
    if (css[i] === '}') depth -= 1
    i += 1
  }
  return css.slice(open + 1, i - 1)
}

describe('CategoryBar.css 手机断点契约（spec §3.3 条件行正常流）', () => {
  const strip = (css: string) => css.replace(/\/\*[\s\S]*?\*\//g, '')
  const barCss = strip(readFileSync(resolve(__dirname, 'CategoryBar.css'), 'utf-8'))
  const chipsCss = strip(readFileSync(resolve(__dirname, 'FilterChips.css'), 'utf-8'))

  it('≤720px：.category-bar 溶解（display:contents），条件行回归正常流', () => {
    const block = mediaBlock(barCss, 'max-width: 720px')
    expect(block).toMatch(/\.category-bar\s*\{[^}]*display:\s*contents/)
  })

  it('≤720px：胶囊行自行 sticky（UI 规范 §6.3 吸顶不变）', () => {
    const block = mediaBlock(barCss, 'max-width: 720px')
    expect(block).toMatch(/\.category-inner\s*\{[^}]*position:\s*sticky/)
    expect(block).toMatch(/\.category-inner\s*\{[^}]*top:\s*var\(--topbar-h\)/)
  })

  it('条件行自身不声明 position（无任何吸附，手机端随内容滚走）', () => {
    expect(chipsCss).not.toContain('position:')
  })
})
