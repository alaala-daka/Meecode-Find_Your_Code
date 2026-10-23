// src/store/feedStore.ts —— 首页信息流分页（规范 §7.1）
import { create } from 'zustand'
import { api } from '../api/client'
import { filterKey as makeFilterKey, type RepoFilters } from '../lib/repoFilters'
import type { RepoCardData } from '../api/types'

interface FeedState {
  cards: RepoCardData[]
  total: number
  loading: boolean
  error: string | null
  hasMore: boolean
  page: number
  category: string | null
  filters: RepoFilters
  filterKey: string
  load: (category: string | null, filters?: RepoFilters) => Promise<void>
  loadMore: () => Promise<void>
  reset: () => void
}

export const useFeedStore = create<FeedState>((set, get) => ({
  cards: [],
  total: 0,
  loading: false,
  error: null,
  hasMore: true,
  page: 0,
  category: null,
  filters: {},
  filterKey: '',
  load: async (category, filters = {}) => {
    set({ loading: true, error: null, category, filters, filterKey: makeFilterKey(filters),
          cards: [], total: 0, page: 1 })
    try {
      const page = await api.feed(category, 1, filters)
      set({ cards: page.cards, hasMore: page.has_more, total: page.total, loading: false })
    } catch (e) {
      set({ loading: false, error: e instanceof Error ? e.message : '加载失败' })
    }
  },
  loadMore: async () => {
    const { hasMore, loading, page, category, filters, cards } = get()
    if (!hasMore || loading) return
    set({ loading: true })
    try {
      const next = await api.feed(category, page + 1, filters)
      set({ cards: [...cards, ...next.cards], hasMore: next.has_more,
            total: next.total, page: page + 1, loading: false })
    } catch (e) {
      set({ loading: false, error: e instanceof Error ? e.message : '加载失败' })
    }
  },
  reset: () => set({ cards: [], total: 0, loading: false, error: null, hasMore: true,
                     page: 0, category: null, filters: {}, filterKey: '' }),
}))
