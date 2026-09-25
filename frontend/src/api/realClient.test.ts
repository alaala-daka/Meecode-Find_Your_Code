// src/api/realClient.test.ts —— 用 stub fetch 验证 URL/方法/凭证与错误透传
import { afterEach, describe, expect, it, vi } from 'vitest'
import { createRealClient } from './realClient'

function stubFetch(body: unknown, ok = true, status = 200) {
  // 每次调用返回全新 Response：Response 体只能读一次，同一实例无法供多次请求复用
  return vi.fn().mockImplementation(() =>
    new Response(JSON.stringify(body), { status: ok ? 200 : status,
      headers: { 'Content-Type': 'application/json' } }))
}

afterEach(() => vi.unstubAllGlobals())

describe('realClient', () => {
  it('feed 带 category/page 且带凭证', async () => {
    const f = stubFetch({ cards: [], has_more: false })
    vi.stubGlobal('fetch', f)
    await createRealClient().feed('开发工具', 2)
    expect(f).toHaveBeenCalledWith('/api/feed?category=%E5%BC%80%E5%8F%91%E5%B7%A5%E5%85%B7&page=2',
      expect.objectContaining({ credentials: 'include' }))
  })

  it('search 透传 sort', async () => {
    const f = stubFetch({ cards: [], has_more: false, total: 0 })
    vi.stubGlobal('fetch', f)
    await createRealClient().search('kv', 'stars', 1)
    expect(f).toHaveBeenCalledWith('/api/search?q=kv&sort=stars&page=1', expect.anything())
  })

  it('错误响应透出后端 detail', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ detail: '未知分类:xx' }), { status: 422 })))
    await expect(createRealClient().feed('xx', 1)).rejects.toThrow('未知分类:xx')
  })

  it('repoTree/repoFile/related 走正确端点', async () => {
    const f = stubFetch([])
    vi.stubGlobal('fetch', f)
    const c = createRealClient()
    await c.repoTree(3); await c.repoFile(3, 'README.md'); await c.related(3)
    const urls = f.mock.calls.map((x) => x[0] as string)
    expect(urls).toEqual(['/api/repos/3/tree', '/api/repos/3/files?path=README.md', '/api/repos/3/related'])
  })

  it('interact 发送显式 active', async () => {
    const f = stubFetch({ active: true })
    vi.stubGlobal('fetch', f)
    await createRealClient().interact(5, 'like', true)
    expect(f).toHaveBeenCalledWith('/api/interactions',
      expect.objectContaining({ method: 'POST', body: JSON.stringify({ repo_id: 5, kind: 'like', active: true }) }))
  })

  it('me 未登录透传 JSON null', async () => {
    const f = stubFetch(null)
    vi.stubGlobal('fetch', f)
    expect(await createRealClient().me()).toBeNull()
    expect(f).toHaveBeenCalledWith('/api/me', expect.objectContaining({ credentials: 'include' }))
  })

  it('me 已登录返回用户对象', async () => {
    const user = { id: 7, login: 'alice', avatar_url: 'a.png', bio: '在写小而可读的系统软件。' }
    const f = stubFetch(user)
    vi.stubGlobal('fetch', f)
    expect(await createRealClient().me()).toEqual(user)
  })

  it('logout POST /api/auth/logout 清会话', async () => {
    const f = stubFetch({ ok: true })
    vi.stubGlobal('fetch', f)
    await createRealClient().logout()
    expect(f).toHaveBeenCalledWith('/api/auth/logout',
      expect.objectContaining({ method: 'POST', credentials: 'include' }))
  })

  it('comments 拼 repo_id/limit/offset', async () => {
    const f = stubFetch({ items: [], total: 0 })
    vi.stubGlobal('fetch', f)
    await createRealClient().comments(3, 10, 20)
    expect(f).toHaveBeenCalledWith('/api/comments?repo_id=3&limit=10&offset=20',
      expect.objectContaining({ credentials: 'include' }))
  })

  it('postComment 发送 repo_id/content/parent_id 并返回 Comment', async () => {
    const f = stubFetch({
      id: 9, repo_id: 1, user_id: 2, user_login: 'u', user_avatar: '',
      parent_id: null, content: 'hi', status: 'pending', created_at: 1, created_at_iso: 'x',
    })
    vi.stubGlobal('fetch', f)
    const out = await createRealClient().postComment(1, 'hi')
    expect(out.status).toBe('pending')
    expect(f).toHaveBeenCalledWith('/api/comments',
      expect.objectContaining({
        method: 'POST',
        body: JSON.stringify({ repo_id: 1, content: 'hi', parent_id: null }),
      }))
  })

  it('deleteComment/hideComment 命中正确端点与方法', async () => {
    const f = stubFetch({ ok: true })
    vi.stubGlobal('fetch', f)
    const c = createRealClient()
    await c.deleteComment(7)
    await c.hideComment(7)
    const calls = f.mock.calls.map((x) => [x[0] as string, (x[1] as RequestInit)?.method])
    expect(calls).toEqual([
      ['/api/comments/7', 'DELETE'],
      ['/api/comments/7/hide', 'POST'],
    ])
  })
})
