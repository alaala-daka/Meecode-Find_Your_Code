// src/store/notificationStore.test.ts —— 铃铛未读数 store：失败吞异常不伪造
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { useNotificationStore } from './notificationStore'

describe('notificationStore', () => {
  beforeEach(() => {
    useNotificationStore.setState({ count: 0 })
  })

  it('refresh 取回未读数', async () => {
    const { api } = await import('../api/client')
    vi.spyOn(api, 'unreadReplyCount').mockResolvedValue({ count: 3 })
    await useNotificationStore.getState().refresh()
    expect(useNotificationStore.getState().count).toBe(3)
    vi.restoreAllMocks()
  })

  it('refresh 失败回落 0 且不抛', async () => {
    const { api } = await import('../api/client')
    vi.spyOn(api, 'unreadReplyCount').mockRejectedValue(new Error('offline'))
    await expect(useNotificationStore.getState().refresh()).resolves.toBeUndefined()
    expect(useNotificationStore.getState().count).toBe(0)
    vi.restoreAllMocks()
  })
})
