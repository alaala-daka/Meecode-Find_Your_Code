// src/api/mockClient.test.ts
import { describe, expect, it } from 'vitest'
import { createMockClient } from './mockClient'

describe('mockClient', () => {
  it('feed 首页 8 条且可翻页', async () => {
    const api = createMockClient()
    const p1 = await api.feed(null, 1)
    const p2 = await api.feed(null, 2)
    expect(p1.cards).toHaveLength(8)
    expect(p1.has_more).toBe(true)
    expect(p2.cards).toHaveLength(4)
    expect(p2.has_more).toBe(false)
  })
  it('feed 按分类过滤', async () => {
    const api = createMockClient()
    const page = await api.feed('AI 与机器学习', 1)
    expect(page.cards.length).toBeGreaterThan(0)
    expect(page.cards.every((c) => c.category === 'AI 与机器学习')).toBe(true)
  })
  it('search 命中 tagline 与 star 排序', async () => {
    const api = createMockClient()
    const hit = await api.search('Agent', 'default', 1)
    expect(hit.total).toBeGreaterThan(0)
    const byStars = await api.search('a', 'stars', 1)
    const stars = byStars.cards.map((c) => c.stars)
    expect(stars).toEqual([...stars].sort((x, y) => y - x))
  })
  it('投稿后出现在 myRepos 顶部', async () => {
    const api = createMockClient()
    const before = (await api.myRepos()).length
    await api.submitRepo({ full_name: 'alice/new-repo', tagline_zh: '新仓库', intro_zh: '', category: '开发工具', cover_url: null })
    const after = await api.myRepos()
    expect(after.length).toBe(before + 1)
    expect(after[0].full_name).toBe('alice/new-repo')
  })
  it('interact 点赞切换计数', async () => {
    const api = createMockClient()
    const before = (await api.repo(2)).likes
    await api.interact(2, 'like', true)
    expect((await api.repo(2)).likes).toBe(before + 1)
  })
  it('repo 详情自带 liked/favorited 回显并随 interact 更新', async () => {
    const api = createMockClient()
    expect((await api.repo(1)).liked).toBe(true)      // fixture 预置点赞 repo 1
    expect((await api.repo(1)).favorited).toBe(false)
    expect((await api.repo(3)).favorited).toBe(true)  // fixture 预置收藏 repo 3
    await api.interact(1, 'like', false)
    expect((await api.repo(1)).liked).toBe(false)
  })
  it('interact 收藏切换 favorites_count 计数', async () => {
    const api = createMockClient()
    const before = (await api.repo(2)).favorites_count!
    await api.interact(2, 'favorite', true)
    expect((await api.repo(2)).favorites_count).toBe(before + 1)
    await api.interact(2, 'favorite', false)
    expect((await api.repo(2)).favorites_count).toBe(before)
  })
  it('delist 后仓库消失', async () => {
    const api = createMockClient()
    await api.delist(1)
    await expect(api.repo(1)).rejects.toThrow('仓库不存在')
  })
  it('related：同分类 stars 降序、排除自身、至多 3 条', async () => {
    const api = createMockClient()
    // fixture：AI 与机器学习 只有 1(128★) 与 6(210★)，排除自身(1)剩 llm-eval-kit
    const rel = await api.related(1)
    expect(rel.map((r) => r.id)).toEqual([6])
  })
  it('related：同分类仅自身时返回空数组（严格不跨类补位，决策 #7）', async () => {
    const api = createMockClient()
    expect(await api.related(11)).toEqual([]) // 其他 分类仅 pixel-sort 自己
  })
  it('aiDraft 返回基于仓库内容的分类推荐', async () => {
    const api = createMockClient()
    // mini-agent：topics agent/llm/runtime → AI 与机器学习
    expect((await api.aiDraft(1)).suggested_category).toBe('AI 与机器学习')
    // dot-snap：topics backup/dotfiles → 开发工具（效率脚本已并入该类）
    expect((await api.aiDraft(5)).suggested_category).toBe('开发工具')
  })
  it('related：仓库不存在 reject', async () => {
    const api = createMockClient()
    await expect(api.related(999)).rejects.toThrow('仓库不存在')
  })
  it('me 恒返回模拟用户，logout 为空操作（mock 无会话概念）', async () => {
    const api = createMockClient()
    expect(await api.me()).toEqual({ id: 0, login: 'alice', avatar_url: '', bio: '在写小而可读的系统软件。' })
    await api.logout()
    expect((await api.me())?.login).toBe('alice')
  })
})
