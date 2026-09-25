// src/api/mockClient.ts
import {
  CATEGORIES, FIXTURE_FILES, FIXTURE_REPOS, FIXTURE_TREE, FIXTURE_USER,
} from './fixtures'
import type {
  AiDraftResult, ApiClient, Comment, CommentPage, CurrentUser, FeedPage, InteractKind,
  MyGithubRepo, RepoCardData, RepoDetail, RepoFile, RepoTreeItem, SearchResult, SubmitPayload, UserProfile,
} from './types'

const PAGE_SIZE = 8

// AI 分类推荐（mock 规则）：按 topics/仓库名/语言命中关键词计分，取最高分分类；真实后端就绪后由 LLM 给出
const CATEGORY_KEYWORDS: Array<[string, string[]]> = [
  ['AI 与机器学习', ['ai', 'llm', 'agent', 'gpt', 'ml', 'eval', 'rag', 'model']],
  // 效率脚本类已并入后端 8 类的「开发工具」，关键词随迁保证 dot-snap 类仓库仍可推荐
  ['开发工具', ['git', 'hook', 'cli', 'lint', 'debug', 'markdown', 'slides', 'sdk', 'editor',
    'backup', 'dotfiles', 'script', 'shell', 'automation', 'workflow']],
  ['Web 应用', ['web', 'http', 'fetch', 'blog', 'vitepress', 'server', 'router', 'ui']],
  ['系统与底层', ['kv', 'storage', 'rust', 'wasm', 'os', 'kernel', 'runtime', 'db', 'cache']],
  ['数据处理', ['csv', 'sql', 'data', 'etl', 'query', 'performance']],
]

function suggestCategory(card: RepoCardData): string {
  const tokens = new Set(
    [card.title, card.language ?? '', ...card.topics]
      .join(' ')
      .toLowerCase()
      .split(/[^a-z0-9]+/)
      .filter(Boolean),
  )
  let best = CATEGORIES[0]
  let bestScore = 0
  for (const [cat, keywords] of CATEGORY_KEYWORDS) {
    const score = keywords.reduce((n, k) => n + (tokens.has(k) ? 1 : 0), 0)
    if (score > bestScore) {
      best = cat
      bestScore = score
    }
  }
  return best
}

function toDetail(card: RepoCardData, liked = false, favorited = false): RepoDetail {
  return {
    ...card,
    intro_zh: `${card.tagline_zh}。这里放详细介绍，介绍作者在投稿时可以自由编辑。`,
    github_url: `https://github.com/${card.full_name}`,
    default_branch: 'main',
    liked,
    favorited,
    is_owner: true, // mock 恒同用户
  }
}

export function createMockClient(): ApiClient {
  const state = {
    repos: [...FIXTURE_REPOS],
    favorites: new Set<number>([3]),
    likes: new Set<number>([1]),
    history: [2, 1],
    bio: FIXTURE_USER.bio,
    comments: [] as Comment[],
    nextCommentId: 1,
  }
  return {
    async categories() {
      return CATEGORIES
    },
    async feed(category, page): Promise<FeedPage> {
      const all = category
        ? state.repos.filter((r) => r.category === category)
        : state.repos
      const start = (page - 1) * PAGE_SIZE
      const cards = all.slice(start, start + PAGE_SIZE)
      return { cards, has_more: start + PAGE_SIZE < all.length }
    },
    async search(q, sort, page): Promise<SearchResult> {
      const kw = q.toLowerCase()
      let hit = state.repos.filter(
        (r) =>
          r.title.toLowerCase().includes(kw) ||
          r.tagline_zh.includes(q) ||
          r.topics.some((t) => t.includes(kw)),
      )
      if (sort === 'newest') {
        hit = [...hit].sort((a, b) => b.published_at.localeCompare(a.published_at))
      } else if (sort === 'stars') {
        hit = [...hit].sort((a, b) => b.stars - a.stars)
      }
      const start = (page - 1) * PAGE_SIZE
      return { total: hit.length, cards: hit.slice(start, start + PAGE_SIZE), has_more: start + PAGE_SIZE < hit.length }
    },
    async repo(id): Promise<RepoDetail> {
      const card = state.repos.find((r) => r.id === id)
      if (!card) throw new Error('仓库不存在')
      return toDetail(card, state.likes.has(id), state.favorites.has(id))
    },
    async repoTree(): Promise<RepoTreeItem[]> {
      return FIXTURE_TREE
    },
    async repoFile(_id, path): Promise<RepoFile> {
      const content = FIXTURE_FILES[path]
      if (content === undefined) throw new Error('文件不存在')
      return { path, content }
    },
    async related(repoId): Promise<RepoCardData[]> {
      const self = state.repos.find((r) => r.id === repoId)
      if (!self) throw new Error('仓库不存在')
      return state.repos
        .filter((r) => r.category === self.category && r.id !== repoId)
        .sort((a, b) => b.stars - a.stars)
        .slice(0, 3)
    },
    async myRepos(): Promise<MyGithubRepo[]> {
      return state.repos
        .filter((r) => r.owner_login === FIXTURE_USER.login)
        .map((r) => ({
          github_id: r.id, full_name: r.full_name, title: r.title,
          language: r.language, stars: r.stars,
          status: r.source === 'submitted' ? 'published' as const : 'pending_claim' as const,
        }))
    },
    async submitRepo(payload: SubmitPayload): Promise<RepoCardData> {
      const next: RepoCardData = {
        id: state.repos.length + 1,
        full_name: payload.full_name,
        title: payload.full_name.split('/')[1],
        owner_login: FIXTURE_USER.login,
        language: 'Python',
        topics: [],
        stars: 0, views: 0, likes: 0, favorites_count: 0,
        source: 'submitted',
        category: payload.category,
        tagline_zh: payload.tagline_zh,
        published_at: new Date().toISOString(),
        cover_url: payload.cover_url,
      }
      state.repos = [next, ...state.repos]
      return next
    },
    async aiDraft(repoId): Promise<AiDraftResult> {
      const card = state.repos.find((r) => r.id === repoId)
      return {
        tagline_zh: card ? card.tagline_zh : '一句话卖点（AI 草稿）',
        intro_zh: '这里是 AI 读 README 后生成的介绍草稿，作者可以任意修改。',
        suggested_category: card ? suggestCategory(card) : CATEGORIES[0],
      }
    },
    async userProfile(login): Promise<UserProfile> {
      return { ...FIXTURE_USER, login }
    },
    async userRepos(login): Promise<RepoCardData[]> {
      return state.repos.filter((r) => r.owner_login === login)
    },
    async userFavorites(): Promise<RepoCardData[]> {
      return state.repos.filter((r) => state.favorites.has(r.id))
    },
    async userHistory(): Promise<RepoCardData[]> {
      return state.history
        .map((id) => state.repos.find((r) => r.id === id))
        .filter((r): r is RepoCardData => Boolean(r))
    },
    async setBio(bio) {
      state.bio = bio
    },
    async interact(repoId, kind: InteractKind, on) {
      const set = kind === 'like' ? state.likes : state.favorites
      if (on) set.add(repoId); else set.delete(repoId)
      const card = state.repos.find((r) => r.id === repoId)
      if (card && kind === 'like') card.likes += on ? 1 : -1
      if (card && kind === 'favorite' && card.favorites_count !== undefined) card.favorites_count += on ? 1 : -1
    },
    async comments(repoId): Promise<CommentPage> {
      const all = state.comments.filter((c) => c.repo_id === repoId && c.status !== 'deleted')
      const tops = all.filter((c) => c.parent_id === null)
      const items = tops.flatMap((t) => [
        t,
        ...all.filter((c) => c.parent_id === t.id).sort((a, b) => a.created_at - b.created_at),
      ])
      return { items, total: tops.length }
    },
    async postComment(repoId, content, parentId = null): Promise<Comment> {
      const id = state.nextCommentId++
      const now = Math.floor(Date.now() / 1000)
      const item: Comment = {
        id, repo_id: repoId, user_id: 0, user_login: FIXTURE_USER.login,
        user_avatar: FIXTURE_USER.avatar_url,
        parent_id: parentId ?? null, content, status: 'pending',
        created_at: now, created_at_iso: new Date(now * 1000).toISOString(),
      }
      state.comments.push(item)
      const snapshot: Comment = { ...item }   // 响应体恒 pending（模拟异步预审）
      const hit = /垃圾|广告|刷屏/.test(content)
      item.status = hit ? 'hidden' : 'visible'  // 内存行立即判定，下一次 GET 即终态
      return snapshot
    },
    async deleteComment(commentId) {
      const row = state.comments.find((c) => c.id === commentId)
      if (row) row.status = 'deleted'
    },
    async hideComment(commentId) {
      const row = state.comments.find((c) => c.id === commentId)
      if (row && row.status !== 'deleted') row.status = 'hidden'
    },
    async delist(repoId) {
      state.repos = state.repos.filter((r) => r.id !== repoId)
    },
    loginUrl(): string {
      return '/api/auth/github'
    },
    async me(): Promise<CurrentUser | null> {
      // mock 无会话概念：恒返回模拟用户（映射为 CurrentUser 形状），保证投稿/收藏等演示流程可用；
      // 纯 mock dev 下点登录会真实跳转 /api/auth/github 并 404，属既有 mock 局限（不造假后端）
      return {
        id: 0, // 模拟用户无真实 id
        login: FIXTURE_USER.login,
        avatar_url: FIXTURE_USER.avatar_url,
        bio: FIXTURE_USER.bio,
      }
    },
    async logout() {
      // mock 无会话状态可清：登出为空操作
    },
  }
}
