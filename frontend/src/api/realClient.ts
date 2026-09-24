// src/api/realClient.ts —— 真实后端客户端:fetch('/api/...') + cookie 凭证
import type {
  AiDraftResult, ApiClient, CurrentUser, FeedPage, InteractKind, MyGithubRepo, RepoCardData,
  RepoDetail, RepoFile, RepoTreeItem, SearchResult, SubmitPayload, UserProfile,
} from './types'

async function http<T>(path: string, init?: RequestInit): Promise<T> {
  const resp = await fetch(path, { credentials: 'include', ...init })
  if (!resp.ok) {
    let detail = `HTTP ${resp.status}`
    try {
      const body = await resp.json()
      if (body && typeof body.detail === 'string') detail = body.detail
    } catch { /* 非 JSON 错误体,保留状态码文案 */ }
    throw new Error(detail)
  }
  return resp.json() as Promise<T>
}

function jsonInit(method: string, body?: unknown): RequestInit {
  return {
    method,
    headers: body === undefined ? undefined : { 'Content-Type': 'application/json' },
    body: body === undefined ? undefined : JSON.stringify(body),
  }
}

export function createRealClient(): ApiClient {
  return {
    async categories() {
      return http<string[]>('/api/categories')
    },
    async feed(category, page): Promise<FeedPage> {
      const qs = new URLSearchParams()
      if (category) qs.set('category', category)
      qs.set('page', String(page))
      return http<FeedPage>(`/api/feed?${qs}`)
    },
    async search(q, sort, page): Promise<SearchResult> {
      const qs = new URLSearchParams({ q, sort, page: String(page) })
      return http<SearchResult>(`/api/search?${qs}`)
    },
    async repo(id): Promise<RepoDetail> {
      return http<RepoDetail>(`/api/repos/${id}`)
    },
    async repoTree(id): Promise<RepoTreeItem[]> {
      return http<RepoTreeItem[]>(`/api/repos/${id}/tree`)
    },
    async repoFile(id, path): Promise<RepoFile> {
      return http<RepoFile>(`/api/repos/${id}/files?path=${encodeURIComponent(path)}`)
    },
    async related(repoId): Promise<RepoCardData[]> {
      return http<RepoCardData[]>(`/api/repos/${repoId}/related`)
    },
    async myRepos(): Promise<MyGithubRepo[]> {
      return http<MyGithubRepo[]>('/api/my/github-repos')
    },
    async submitRepo(payload: SubmitPayload): Promise<RepoCardData> {
      return http<RepoCardData>('/api/submit', jsonInit('POST', payload))
    },
    async aiDraft(repoId): Promise<AiDraftResult> {
      return http<AiDraftResult>('/api/ai-draft', jsonInit('POST', { github_id: repoId }))
    },
    async userProfile(login): Promise<UserProfile> {
      return http<UserProfile>(`/api/users/${encodeURIComponent(login)}/profile`)
    },
    async userRepos(login): Promise<RepoCardData[]> {
      return http<RepoCardData[]>(`/api/users/${encodeURIComponent(login)}/repos`)
    },
    async userFavorites(login): Promise<RepoCardData[]> {
      return http<RepoCardData[]>(`/api/users/${encodeURIComponent(login)}/favorites`)
    },
    async userHistory(login): Promise<RepoCardData[]> {
      return http<RepoCardData[]>(`/api/users/${encodeURIComponent(login)}/history`)
    },
    async setBio(bio) {
      await http('/api/me/bio', jsonInit('PUT', { bio }))
    },
    async interact(repoId, kind: InteractKind, on) {
      await http('/api/interactions', jsonInit('POST', { repo_id: repoId, kind, active: on }))
    },
    async delist(repoId) {
      await http(`/api/repos/${repoId}/delist`, jsonInit('POST'))
    },
    loginUrl(): string {
      return '/api/auth/github'
    },
    async me(): Promise<CurrentUser | null> {
      // 未登录时后端返回 JSON null，直接透传给会话引导
      return http<CurrentUser | null>('/api/me')
    },
    async logout() {
      await http('/api/auth/logout', jsonInit('POST'))
    },
  }
}
