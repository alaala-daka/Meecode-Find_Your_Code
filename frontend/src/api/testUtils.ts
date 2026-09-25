// src/api/testUtils.ts —— 测试辅助：card → detail（与 mockClient.toDetail 同规则）
import type { RepoCardData, RepoDetail } from './types'
import { FIXTURE_REPOS } from './fixtures'

export function toDetail(id: number): RepoDetail {
  const card: RepoCardData = FIXTURE_REPOS.find((r) => r.id === id)!
  if (!card) throw new Error(`fixture 缺少 id=${id}`)
  return {
    ...card,
    intro_zh: `${card.tagline_zh}。这里放详细介绍，介绍作者在投稿时可以自由编辑。`,
    github_url: `https://github.com/${card.full_name}`,
    default_branch: 'main',
    liked: false,
    favorited: false,
  }
}
