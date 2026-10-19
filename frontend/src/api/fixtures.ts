// src/api/fixtures.ts —— 确定性数据，测试与开发共用
import type { FeedbackDetail, RepoCardData, RepoTreeItem, UserProfile } from './types'

export const CATEGORIES = [
  '开发工具', 'Web 应用', 'AI 与机器学习', '系统与底层',
  '数据处理', '游戏与图形', '学习资源', '其他',
]

const DAY = 86400_000
const now = Date.UTC(2026, 7, 25, 12, 0, 0) // 2026-08-25 12:00 UTC，固定基准保证确定性
const iso = (daysAgo: number) => new Date(now - daysAgo * DAY).toISOString()

export const FIXTURE_REPOS: RepoCardData[] = [
  { id: 1, full_name: 'alice/mini-agent', title: 'mini-agent', owner_login: 'alice', language: 'Python', topics: ['agent', 'llm', 'runtime'], stars: 128, views: 3100, likes: 45, source: 'submitted', category: 'AI 与机器学习', tagline_zh: '给 LLM Agent 的最小运行时，200 行可读完', published_at: iso(1), cover_url: null, favorites_count: 24 },
  { id: 2, full_name: 'bob/tinyfetch', title: 'tinyfetch', owner_login: 'bob', language: 'TypeScript', topics: ['http', 'fetch'], stars: 56, views: 980, likes: 12, source: 'crawled', category: 'Web 应用', tagline_zh: '比 fetch 更顺手的请求封装，零依赖', published_at: iso(2), cover_url: null, favorites_count: 5 },
  { id: 3, full_name: 'carol/rust-kv', title: 'rust-kv', owner_login: 'carol', language: 'Rust', topics: ['kv', 'storage'], stars: 340, views: 5200, likes: 88, source: 'submitted', category: '系统与底层', tagline_zh: '教学向键值存储，从日志到快照一步步搭', published_at: iso(3), cover_url: null, favorites_count: 40 },
  { id: 4, full_name: 'dave/csv-crunch', title: 'csv-crunch', owner_login: 'dave', language: 'Go', topics: ['csv', 'cli'], stars: 77, views: 1200, likes: 20, source: 'crawled', category: '数据处理', tagline_zh: '命令行里把 CSV 揉成任何形状', published_at: iso(5), cover_url: null, favorites_count: 9 },
  { id: 5, full_name: 'erin/dot-snap', title: 'dot-snap', owner_login: 'erin', language: 'Shell', topics: ['backup', 'dotfiles'], stars: 23, views: 400, likes: 6, source: 'crawled', category: '开发工具', tagline_zh: '一条命令备份并恢复你的 dotfiles', published_at: iso(8), cover_url: null, favorites_count: 3 },
  { id: 6, full_name: 'frank/llm-eval-kit', title: 'llm-eval-kit', owner_login: 'frank', language: 'Python', topics: ['eval', 'llm'], stars: 210, views: 4100, likes: 61, source: 'submitted', category: 'AI 与机器学习', tagline_zh: '本地跑通 LLM 评测的最小工具箱', published_at: iso(0.2), cover_url: null, favorites_count: 22 },
  { id: 7, full_name: 'grace/vitepress-blog', title: 'vitepress-blog', owner_login: 'grace', language: 'JavaScript', topics: ['blog', 'vitepress'], stars: 41, views: 700, likes: 9, source: 'crawled', category: 'Web 应用', tagline_zh: '开箱即写的博客模板，部署只要三分钟', published_at: iso(12), cover_url: null, favorites_count: 6 },
  { id: 8, full_name: 'henry/sql-tuner', title: 'sql-tuner', owner_login: 'henry', language: 'Java', topics: ['sql', 'performance'], stars: 95, views: 1800, likes: 27, source: 'crawled', category: '数据处理', tagline_zh: '把慢查询指给你看，再给你改法', published_at: iso(20), cover_url: null, favorites_count: 15 },
  { id: 9, full_name: 'ivy/git-hook-lite', title: 'git-hook-lite', owner_login: 'ivy', language: 'Go', topics: ['git', 'hooks'], stars: 33, views: 520, likes: 8, source: 'submitted', category: '开发工具', tagline_zh: '不装 node 也能用的 git hooks 管理器', published_at: iso(0.5), cover_url: null, favorites_count: 7 },
  { id: 10, full_name: 'jack/md-slide', title: 'md-slide', owner_login: 'jack', language: 'TypeScript', topics: ['markdown', 'slides'], stars: 150, views: 2600, likes: 40, source: 'crawled', category: '开发工具', tagline_zh: 'Markdown 直接变幻灯片的极简方案', published_at: iso(30), cover_url: null, favorites_count: 18 },
  { id: 11, full_name: 'kate/pixel-sort', title: 'pixel-sort', owner_login: 'kate', language: 'Kotlin', topics: ['glitch', 'image'], stars: 18, views: 300, likes: 4, source: 'crawled', category: '其他', tagline_zh: '像素排序故障艺术，参数随手调', published_at: iso(45), cover_url: null, favorites_count: 2 },
  { id: 12, full_name: 'leo/wasm-notes', title: 'wasm-notes', owner_login: 'leo', language: 'C++', topics: ['wasm'], stars: 64, views: 1100, likes: 15, source: 'submitted', category: '系统与底层', tagline_zh: '从零编译到浏览器的 WASM 笔记工程', published_at: iso(60), cover_url: null, favorites_count: 10 },
]

export const FIXTURE_USER: UserProfile = {
  login: 'alice',
  avatar_url: '',
  bio: '在写小而可读的系统软件。',
  repo_count: 2,
  star_count: 338,
  favorite_count: 24,
}

export const FIXTURE_TREE: RepoTreeItem[] = [
  { name: 'README.md', path: 'README.md', type: 'file' },
  { name: 'assets', path: 'assets', type: 'dir', size: 0, children: [
    { name: 'logo.png', path: 'assets/logo.png', type: 'file', size: 4096 },
    { name: 'logo.svg', path: 'assets/logo.svg', type: 'file', size: 800 },
    { name: 'huge.png', path: 'assets/huge.png', type: 'file', size: 6 * 1024 * 1024 },
  ] },
  { name: 'src', path: 'src', type: 'dir', children: [
    { name: 'main.py', path: 'src/main.py', type: 'file' },
    { name: 'loop.py', path: 'src/loop.py', type: 'file' },
  ] },
  { name: 'docs', path: 'docs', type: 'dir', size: 0, children: [
    { name: 'report.pdf', path: 'docs/report.pdf', type: 'file', size: 500_000 },
  ] },
  { name: 'big.log', path: 'big.log', type: 'file', size: 250_000 },
]

export const FIXTURE_FILES: Record<string, string> = {
  'README.md': '# mini-agent\n\n200 行的 LLM Agent 运行时。',
  'src/main.py': 'from loop import run\n\nif __name__ == "__main__":\n    run()\n',
  'src/loop.py': 'def run():\n    print("agent loop")\n',
}

// 反馈夹具：一条已处理（含一条未读回复）+ 一条待处理，足够驱动铃铛与列表/详情全态
export const FIXTURE_FEEDBACK: FeedbackDetail[] = [
  {
    id: 1,
    category: 'bug',
    body: '仓库详情页在窄屏下文件树会挤成一团。',
    status: 'done',
    created_at: Math.floor((now - 3 * DAY) / 1000),
    updated_at: Math.floor((now - 1 * DAY) / 1000),
    replies: [
      {
        id: 1,
        body: '已修，感谢反馈！',
        author_login: 'meecode',
        created_at: Math.floor((now - 1 * DAY) / 1000),
      },
    ],
  },
  {
    id: 2,
    category: 'suggest',
    body: '希望首页能按最近更新时间排序。',
    status: 'pending',
    created_at: Math.floor((now - 0.2 * DAY) / 1000),
    updated_at: Math.floor((now - 0.2 * DAY) / 1000),
    replies: [],
  },
]
