// src/store/feedStore.ts —— 首页信息流分页（规范 §7.1）
import { create } from 'zustand'
import { api } from '../api/client'
import type { RepoCardData } from '../api/types'

interface FeedState {
  cards: RepoCardData[]
  loading: boolean
  error: string | null
  hasMore: boolean
  page: number
  category: string | null
  load: (category: string | null) => Promise<void>
  loadMore: () => Promise<void>
  reset: () => void
}

export const useFeedStore = create<FeedState>((set, get) => ({
  cards: [],
  loading: false,
  error: null,
  hasMore: true,
  page: 0,
  category: null,
  load: async (category) => {
    set({ loading: true, error: null, category, cards: [], page: 1 })
    try {
      const page = await api.feed(category, 1)
      set({ cards: page.cards, hasMore: page.has_more, loading: false })
    } catch (e) {
      set({ loading: false, error: e instanceof Error ? e.message : '加载失败' })
    }
  },
  loadMore: async () => {
    const { hasMore, loading, page, category, cards } = get()
    if (!hasMore || loading) return
    set({ loading: true })
    try {
      const next = await api.feed(category, page + 1)
      set({ cards: [...cards, ...next.cards], hasMore: next.has_more, page: page + 1, loading: false })
    } catch (e) {
      set({ loading: false, error: e instanceof Error ? e.message : '加载失败' })
    }
  },
  reset: () => set({ cards: [], loading: false, error: null, hasMore: true, page: 0, category: null }),
}))
