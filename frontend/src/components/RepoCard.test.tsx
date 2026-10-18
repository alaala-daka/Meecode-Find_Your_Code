// src/components/RepoCard.test.tsx
import { readFileSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'
import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { describe, expect, it } from 'vitest'
import type { RepoCardData } from '../api/types'
import RepoCard from './RepoCard'

// vitest 的 css:false 会把 CSS 导入替换成空字符串，覆盖层契约只能直接读样式表文本
const repoCardCss = readFileSync(join(dirname(fileURLToPath(import.meta.url)), 'RepoCard.css'), 'utf8')

const card: RepoCardData = {
  id: 1, full_name: 'alice/mini-agent', title: 'mini-agent', owner_login: 'alice',
  language: 'Python', topics: ['agent'], stars: 128, views: 3100, likes: 45,
  source: 'submitted', category: 'AI 与机器学习',
  tagline_zh: '给 LLM Agent 的最小运行时', published_at: new Date().toISOString(), cover_url: null,
}

function renderCard(data: RepoCardData) {
  return render(<RepoCard data={data} />, { wrapper: MemoryRouter })
}

describe('RepoCard', () => {
  it('渲染标题、tagline、作者与链接', () => {
    renderCard(card)
    expect(screen.getByText('mini-agent')).toBeInTheDocument()
    expect(screen.getByText('给 LLM Agent 的最小运行时')).toBeInTheDocument()
    expect(screen.getByText('alice')).toBeInTheDocument()
    // 标题链接指向仓库页
    const link = screen.getByRole('link', { name: 'mini-agent' })
    expect(link).toHaveAttribute('href', '/repo/1')
  })
  it('无封面：不渲染图片与 SVG 封面', () => {
    const { container } = renderCard(card)
    expect(container.querySelector('img, svg')).toBeNull()
    expect(container.querySelector('.repo-card-cover')).toBeNull()
  })
  it('元信息行展示 star 数（浏览/点赞不在卡片曝光）', () => {
    renderCard(card)
    expect(screen.getByText('128')).toBeInTheDocument()
    expect(screen.queryByText('3100')).not.toBeInTheDocument()
    expect(screen.queryByText('45')).not.toBeInTheDocument()
  })
  it('投稿与采集角标', () => {
    const { rerender } = renderCard(card)
    expect(screen.getByText('投稿')).toHaveClass('badge-submitted')
    rerender(<RepoCard data={{ ...card, source: 'crawled' }} />)
    expect(screen.getByText('采集')).toHaveClass('badge-crawled')
  })
  it('语言圆点使用语言色', () => {
    const { container } = renderCard(card)
    const dot = container.querySelector('.lang-dot') as HTMLElement
    expect(dot).toBeTruthy()
    expect(dot.style.backgroundColor).not.toBe('')
  })
  it('整卡可点：卡片内只有标题这一个链接，其覆盖层铺满整卡', () => {
    // jsdom 不做命中测试，「点击卡片任意位置进入仓库」由 stretched link 的 CSS 承担，这里钉住该契约
    const { container } = renderCard(card)
    const links = container.querySelectorAll('a')
    expect(links).toHaveLength(1)
    expect(links[0]).toHaveAttribute('href', '/repo/1')
    expect(repoCardCss).toMatch(/\.repo-card-title a::after\s*\{[^}]*position:\s*absolute/)
    expect(repoCardCss).toMatch(/\.repo-card\s*\{[^}]*position:\s*relative/)
  })
  it('interactive={false}（投稿页预览）不渲染链接、不参与跳转', () => {
    render(<RepoCard data={card} interactive={false} />, { wrapper: MemoryRouter })
    expect(screen.queryByRole('link')).toBeNull()
    expect(screen.getByText('mini-agent')).toBeInTheDocument()
    expect(screen.getByText('给 LLM Agent 的最小运行时')).toBeInTheDocument()
    expect(document.querySelector('.repo-card')).toHaveClass('repo-card--static')
  })
})
