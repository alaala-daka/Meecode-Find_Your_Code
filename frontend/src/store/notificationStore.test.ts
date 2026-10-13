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

  it('reset 作废在途 refresh：登出竞态下迟到响应不复活红点', async () => {
    const { api } = await import('../api/client')
    let resolve!: (v: { count: number }) => void
    vi.spyOn(api, 'unreadReplyCount').mockReturnValue(new Promise<{ count: number }>((r) => { resolve = r }))
    const inflight = useNotificationStore.getState().refresh()  // 在途请求
    useNotificationStore.getState().reset()                     // 登出清零（App.tsx !user 分支）
    resolve({ count: 5 })                                       // 迟到响应
    await inflight
    expect(useNotificationStore.getState().count).toBe(0)
    vi.restoreAllMocks()
  })
})
