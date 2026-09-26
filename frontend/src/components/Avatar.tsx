// src/components/Avatar.tsx —— 统一头像：有 avatar_url 用其图，否则用觅码品牌默认头像（圆框/方框双版本），加载失败回退默认
import { useState } from 'react'
import avatarDefaultRound from '../assets/avatar-default.png'
import avatarDefaultSquare from '../assets/avatar-default-square.png'
import './Avatar.css'

interface Props {
  login: string
  avatarUrl?: string
  className?: string
  variant?: 'round' | 'square'
}

export default function Avatar({ login, avatarUrl, className, variant = 'round' }: Props) {
  const [failed, setFailed] = useState(false)
  const avatarDefault = variant === 'square' ? avatarDefaultSquare : avatarDefaultRound
  const src = failed || !avatarUrl ? avatarDefault : avatarUrl
  return (
    <span className={className ? `avatar ${className}` : 'avatar'} role="img" aria-label={`${login} 的头像`}>
      <img
        className="avatar-img"
        src={src}
        alt=""
        loading="lazy"
        onError={() => setFailed(true)}
      />
    </span>
  )
}
