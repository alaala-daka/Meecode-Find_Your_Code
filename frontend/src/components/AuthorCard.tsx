// src/components/AuthorCard.tsx —— 五项改进 §3.5 右栏作者卡
import { Link } from 'react-router-dom'
import Avatar from './Avatar'
import './AuthorCard.css'

interface Props {
  ownerLogin: string
  githubUrl: string
}

export default function AuthorCard({ ownerLogin, githubUrl }: Props) {
  return (
    <section className="author-card" aria-label="仓库作者">
      <div className="author-card-id">
        <Avatar
          login={ownerLogin}
          avatarUrl={`https://github.com/${ownerLogin}.png?size=96`}
          className="author-card-avatar"
          variant="square"
        />
        <span className="author-card-name">{ownerLogin}</span>
      </div>
      <a className="btn btn-secondary author-card-btn" href={githubUrl} target="_blank" rel="noreferrer">跳转 GitHub ↗</a>
      <Link className="btn btn-ghost author-card-btn" to={`/user/${ownerLogin}`}>浏览创作者其他仓库</Link>
    </section>
  )
}
