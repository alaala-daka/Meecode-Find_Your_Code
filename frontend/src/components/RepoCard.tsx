// src/components/RepoCard.tsx —— 纸面墨线卡片：无封面，等宽标题 + 一句话卖点 + 元信息行（star/语言/日期）
// 整卡可点：标题 <Link> 的 ::after 铺满卡片（stretched link，见 RepoCard.css），点击卡片任意位置即进入仓库；
// 卡片内只渲染这一个链接，键盘焦点与可访问名仍是仓库名本身。
// interactive={false} 用于投稿页「卡片预览」等静态展示：不渲染链接、不参与跳转（预览 id 是占位值）。
import { Link } from 'react-router-dom'
import type { RepoCardData } from '../api/types'
import { formatCount, formatTime } from '../utils/format'
import { languageColor } from '../theme/languageColors'
import './RepoCard.css'

export default function RepoCard({ data, interactive = true }: { data: RepoCardData; interactive?: boolean }) {
  return (
    <article className={interactive ? 'repo-card' : 'repo-card repo-card--static'}>
      <div className="repo-card-top">
        <h3 className="repo-card-title">
          {interactive ? <Link to={`/repo/${data.id}`}>{data.title}</Link> : data.title}
        </h3>
        <span className={`source-badge badge-${data.source}`}>
          {data.source === 'submitted' ? '投稿' : '采集'}
        </span>
      </div>
      <p className="repo-card-tagline">{data.tagline_zh}</p>
      <p className="repo-card-meta">
        <span className="meta-author">{data.owner_login}</span>
        <span className="meta-stars">
          <span className="star-icon" aria-hidden="true">★</span>
          {formatCount(data.stars)}
        </span>
        {data.language && (
          <span className="meta-lang">
            <span className="lang-dot" style={{ backgroundColor: languageColor(data.language) }} aria-hidden="true" />
            {data.language}
          </span>
        )}
        <span className="meta-date">{formatTime(data.published_at)}</span>
      </p>
    </article>
  )
}
