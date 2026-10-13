// src/store/notificationStore.ts —— 管理回复未读数：轮询挂 App 级，组件只消费计数
import { create } from 'zustand'
import { api } from '../api/client'

export const POLL_MS = 60_000

interface NotificationState {
  count: number
  refresh: () => Promise<void>
  reset: () => void  // 登出清零专用：递增 generation 作废在途 refresh
}

export const useNotificationStore = create<NotificationState>((set) => {
  let generation = 0  // reset 自增；refresh 捕获后若已变化即丢弃迟到结果
  return {
    count: 0,
    refresh: async () => {
      const gen = generation
      try {
        const r = await api.unreadReplyCount()
        if (gen === generation) set({ count: r.count })
      } catch {
        if (gen === generation) set({ count: 0 })
      }
    },
    reset: () => {
      generation += 1
      set({ count: 0 })
    },
  }
})
