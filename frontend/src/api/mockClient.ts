// src/api/mockClient.ts
import { ApiError } from './errors'
import {
  CATEGORIES, FIXTURE_FEEDBACK, FIXTURE_FILES, FIXTURE_REPOS, FIXTURE_TREE, FIXTURE_USER,
} from './fixtures'
import type {
  AiDraftResult, ApiClient, Comment, CommentPage, CurrentUser, FeedPage, FeedbackDetail,
  FeedbackPayload, InteractKind, InteractResult, MyFeedbackPage, MyGithubRepo, ReplyNotificationPage,
  RepoCardData, RepoDetail, RepoFile, RepoTreeItem, SearchResult, SubmitPayload, UserProfile,
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
    feedback: FIXTURE_FEEDBACK.map((f) => ({ ...f, replies: [...f.replies] })),  // 深一层拷贝：detail 置已读不得污染夹具
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
      // mock 世界的二进制/超大拒绝（与后端 /files 422 同构），供错误文案开发态验证
      if (path === 'docs/report.pdf') throw new ApiError('该文件为二进制，请到 GitHub 查看', 422, 'binary')
      if (path === 'big.log') throw new ApiError('文件过大，请到 GitHub 查看', 422, 'too_large')
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
    async interact(repoId, kind: InteractKind, on, ghSync = true): Promise<InteractResult> {
      const set = kind === 'like' ? state.likes : state.favorites
      if (on) set.add(repoId); else set.delete(repoId)
      const card = state.repos.find((r) => r.id === repoId)
      if (card && kind === 'like') card.likes += on ? 1 : -1
      if (card && kind === 'favorite' && card.favorites_count !== undefined) card.favorites_count += on ? 1 : -1
      // mock 无 token 世界（spec §4.4）：favorite on/off(ghSync) = need_auth；off(仅本地) = kept
      const sync = kind === 'favorite' ? (on ? 'need_auth' : (ghSync ? 'need_auth' : 'kept')) : ''
      return { active: on, sync }
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
        moderation_reason: '',
        created_at: now, created_at_iso: new Date(now * 1000).toISOString(),
      }
      state.comments.push(item)
      const snapshot: Comment = { ...item }   // 响应体恒 pending（模拟异步预审）
      const hit = /垃圾|广告|刷屏/.test(content)
      item.status = hit ? 'hidden' : 'visible'  // 内存行立即判定，下一次 GET 即终态
      if (hit) item.moderation_reason = '命中违规关键词'
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
        gh_star_authed: false,
      }
    },
    async logout() {
      // mock 无会话状态可清：登出为空操作
    },
    async submitFeedback(payload: FeedbackPayload) {
      const sec = Math.floor(Date.now() / 1000)
      const id = Math.max(0, ...state.feedback.map((f) => f.id)) + 1
      state.feedback.unshift({
        id, category: payload.category, body: payload.body, status: 'pending',
        created_at: sec, updated_at: sec, replies: [],
      })
      return { id }
    },
    async myFeedback(page, pageSize = 20): Promise<MyFeedbackPage> {
      const start = (page - 1) * pageSize
      // 对齐真实端点 ORDER BY f.id DESC：夹具插入顺序≠id 顺序，先排序再分页
      const sorted = [...state.feedback].sort((a, b) => b.id - a.id)
      return {
        items: sorted.slice(start, start + pageSize).map((f) => {
          const last = f.replies[f.replies.length - 1] ?? null
          return {
            id: f.id,
            category: f.category,
            body_preview: f.body.slice(0, 60),
            status: f.status,
            created_at: f.created_at,
            updated_at: f.updated_at,
            last_reply_preview: last ? last.body.slice(0, 80) : null,
            last_reply_at: last ? last.created_at : null,
            unread_count: f.replies.filter((r) => r.read_at === undefined).length,
          }
        }),
        total: state.feedback.length,
      }
    },
    async feedback(id): Promise<FeedbackDetail> {
      const hit = state.feedback.find((f) => f.id === id)
      if (!hit) throw new Error('反馈不存在')
      hit.replies = hit.replies.map((r) => ({ ...r, read_at: Math.floor(Date.now() / 1000) }))
      return { ...hit, replies: [...hit.replies] }  // 深一层拷贝返回：调用方改不到内存态
    },
    async replyNotifications(limit = 10): Promise<ReplyNotificationPage> {
      const all = state.feedback
        .flatMap((f) => f.replies.map((r) => ({
          feedback_id: f.id,
          feedback_body_preview: f.body.slice(0, 60),
          reply_id: r.id,
          reply_body_preview: r.body.slice(0, 80),
          created_at: r.created_at,
        })))
        .sort((a, b) => b.reply_id - a.reply_id)
      return { items: all.slice(0, limit), total: all.length }  // total=全量（对齐后端），items 才受 limit 截断
    },
    async unreadReplyCount() {
      return {
        count: state.feedback.reduce(
          (n, f) => n + f.replies.filter((r) => r.read_at === undefined).length, 0),
      }
    },
    async ghStarDisconnect() {
      // mock 无 token 可撤：空操作
    },
  }
}
