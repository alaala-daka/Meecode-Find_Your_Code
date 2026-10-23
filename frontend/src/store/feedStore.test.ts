// src/store/feedStore.test.ts
import { beforeEach, describe, expect, it } from 'vitest'
import { useFeedStore } from './feedStore'

describe('feedStore', () => {
  beforeEach(() => {
    useFeedStore.setState({ cards: [], loading: false, error: null, hasMore: true, page: 0, category: null })
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
