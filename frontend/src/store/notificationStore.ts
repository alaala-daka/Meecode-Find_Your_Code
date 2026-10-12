// src/store/notificationStore.ts —— 管理回复未读数：轮询挂 App 级，组件只消费计数
import { create } from 'zustand'
import { api } from '../api/client'

export const POLL_MS = 60_000

interface NotificationState {
  count: number
  refresh: () => Promise<void>
}

export const useNotificationStore = create<NotificationState>((set) => ({
  count: 0,
  refresh: async () => {
    try {
      const r = await api.unreadReplyCount()
      set({ count: r.count })
    } catch {
      set({ count: 0 })
    }
  },
}))
