// src/store/feedStore.test.ts
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { useFeedStore } from './feedStore'

describe('feedStore', () => {
  beforeEach(() => {
    useFeedStore.setState({ cards: [], total: 0, loading: false, error: null, hasMore: true, page: 0,
      category: null, filters: {}, filterKey: '' })
  })
  it('load 拉第一页，loadMore 追加', async () => {
    await useFeedStore.getState().load(null)
    const first = useFeedStore.getState()
    expect(first.cards).toHaveLength(8)
    expect(first.hasMore).toBe(true)
    await useFeedStore.getState().loadMore()
    expect(useFeedStore.getState().cards).toHaveLength(12)
    expect(useFeedStore.getState().hasMore).toBe(false)
  })
  it('load 重置分类与列表', async () => {
    await useFeedStore.getState().load(null)
    await useFeedStore.getState().load('AI 与机器学习')
    const s = useFeedStore.getState()
    expect(s.category).toBe('AI 与机器学习')
    expect(s.cards.every((c) => c.category === 'AI 与机器学习')).toBe(true)
  })
})

describe('feedStore 过滤', () => {
  it('load 携带 filters 并记录 filterKey/total', async () => {
    const api = (await import('../api/client')).api
    const spy = vi.spyOn(api, 'feed').mockResolvedValue({ cards: [], has_more: false, total: 0 })
    await useFeedStore.getState().load('开发工具', { lang: 'Go', topics: ['cli'] })
    expect(spy).toHaveBeenCalledWith('开发工具', 1, { lang: 'Go', topics: ['cli'] })
    expect(useFeedStore.getState().filterKey).not.toBe('')
    spy.mockRestore()
  })

  it('loadMore 沿用已存 filters', async () => {
    const api = (await import('../api/client')).api
    // has_more: true 才会触发翻页（hasMore=false 时 loadMore 是 no-op），关注点仅为 filters 复用
    const spy = vi.spyOn(api, 'feed').mockResolvedValue({ cards: [], has_more: true, total: 0 })
    await useFeedStore.getState().load(null, { stars: 100 })
    await useFeedStore.getState().loadMore()
    expect(spy).toHaveBeenLastCalledWith(null, 2, { stars: 100 })
    spy.mockRestore()
  })
})
