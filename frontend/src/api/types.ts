// src/api/types.ts —— 全部 DTO（与后端 schemas 对齐，后端就绪后不改前端类型）
export type Source = 'submitted' | 'crawled'
export type SortKey = 'default' | 'newest' | 'stars'
export type InteractKind = 'like' | 'favorite'

export interface RepoCardData {
  id: number
  full_name: string          // owner/repo
  title: string              // 仓库名
  owner_login: string
  language: string | null
  topics: string[]
  stars: number
  views: number
  likes: number
  source: Source
  category: string
  tagline_zh: string
  published_at: string       // ISO
  cover_url: string | null
  favorites_count?: number   // 每仓收藏数；真实后端就绪前后端可缺省，UI 不显数字
}

export interface RepoDetail extends RepoCardData {
  intro_zh: string
  github_url: string
  default_branch: string
  liked: boolean       // 当前用户点赞态；未登录恒 false
  favorited: boolean   // 当前用户收藏态；未登录恒 false
  is_owner: boolean    // 当前用户是否为作者/认领者（canModerate 依据）
}

export type CommentStatus = 'pending' | 'visible' | 'hidden' | 'deleted'

export interface Comment {
  id: number
  repo_id: number
  user_id: number
  user_login: string
  user_avatar: string
  parent_id: number | null
  content: string
  status: CommentStatus
  moderation_reason: string   // 仅 LLM 拒绝时非空：徽标以此区分「未通过审核」与「作者隐藏」
  created_at: number
  created_at_iso: string
}

export interface CommentPage {
  items: Comment[]
  total: number
}

export interface UserProfile {
  login: string
  avatar_url: string
  bio: string
  repo_count: number
  star_count: number
  favorite_count: number
}

export interface FeedPage {
  cards: RepoCardData[]
  has_more: boolean
}

export interface SearchResult extends FeedPage {
  total: number
}

export interface RepoTreeItem {
  name: string
  path: string
  type: 'file' | 'dir'
  children?: RepoTreeItem[]
}

export interface RepoFile {
  path: string
  content: string
}

export interface SubmitPayload {
  full_name: string
  tagline_zh: string
  intro_zh: string
  category: string
  cover_url: string | null
}

export interface AiDraftResult {
  tagline_zh: string
  intro_zh: string
  suggested_category: string // AI 根据仓库内容推荐的分类
}

export interface MyGithubRepo {
  github_id: number
  full_name: string
  title: string
  language: string | null
  stars: number
  status: '' | 'published' | 'pending_claim'
}

// 当前登录用户（对齐后端 GET /api/me 的 UserOut；匿名时接口返回 JSON null）
export interface CurrentUser {
  id: number
  login: string
  avatar_url: string
  bio: string
}

export interface ApiClient {
  categories(): Promise<string[]>
  feed(category: string | null, page: number): Promise<FeedPage>
  search(q: string, sort: SortKey, page: number): Promise<SearchResult>
  repo(id: number): Promise<RepoDetail>
  repoTree(id: number): Promise<RepoTreeItem[]>
  repoFile(id: number, path: string): Promise<RepoFile>
  related(repoId: number): Promise<RepoCardData[]>
  myRepos(): Promise<MyGithubRepo[]>
  submitRepo(payload: SubmitPayload): Promise<RepoCardData>
  aiDraft(repoId: number): Promise<AiDraftResult>
  userProfile(login: string): Promise<UserProfile>
  userRepos(login: string): Promise<RepoCardData[]>
  userFavorites(login: string): Promise<RepoCardData[]>
  userHistory(login: string): Promise<RepoCardData[]>
  setBio(bio: string): Promise<void>
  interact(repoId: number, kind: InteractKind, on: boolean): Promise<void>
  comments(repoId: number, limit?: number, offset?: number): Promise<CommentPage>
  postComment(repoId: number, content: string, parentId?: number | null): Promise<Comment>
  deleteComment(commentId: number): Promise<void>
  hideComment(commentId: number): Promise<void>
  delist(repoId: number): Promise<void>
  loginUrl(): string
  me(): Promise<CurrentUser | null> // GET /api/me：会话引导，未登录返回 null
  logout(): Promise<void>           // POST /api/auth/logout：清除会话 cookie
}
