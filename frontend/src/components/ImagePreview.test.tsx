// src/components/ImagePreview.test.tsx
import { fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import ImagePreview from './ImagePreview'

const BASE = {
  fullName: 'owner/repo',
  defaultBranch: 'main',
  githubUrl: 'https://github.com/owner/repo',
}

describe('ImagePreview', () => {
  it('渲染 raw 直链 <img>（SVG 同通道，不内联）', () => {
    render(<ImagePreview path="assets/logo.svg" {...BASE} size={800} />)
    const img = screen.getByRole('img')
    expect(img).toHaveAttribute('src', 'https://raw.githubusercontent.com/owner/repo/main/assets/logo.svg')
  })

  it('头部给出该文件的 GitHub 深链', () => {
    render(<ImagePreview path="assets/logo.svg" {...BASE} size={800} />)
    expect(screen.getByRole('link', { name: '在 GitHub 查看 ↗' }))
      .toHaveAttribute('href', 'https://github.com/owner/repo/blob/main/assets/logo.svg')
  })

  it('加载失败降级为「图片加载失败」并保留 GitHub 链接', () => {
    render(<ImagePreview path="assets/logo.svg" {...BASE} size={800} />)
    fireEvent.error(screen.getByRole('img'))
    expect(screen.getByText(/图片加载失败/)).toBeInTheDocument()
    expect(screen.getByRole('link', { name: '去 GitHub 查看 ↗' })).toBeInTheDocument()
    expect(screen.queryByRole('img')).not.toBeInTheDocument()
  })

  it('切换 path 后失败态复位，对新图片重新尝试加载', () => {
    const { rerender } = render(<ImagePreview path="assets/a.png" {...BASE} size={800} />)
    fireEvent.error(screen.getByRole('img'))
    expect(screen.getByText(/图片加载失败/)).toBeInTheDocument()
    rerender(<ImagePreview path="assets/b.png" {...BASE} size={800} />)
    const img = screen.getByRole('img')
    expect(img).toHaveAttribute('src', 'https://raw.githubusercontent.com/owner/repo/main/assets/b.png')
    expect(screen.queryByText(/图片加载失败/)).not.toBeInTheDocument()
  })

  it('超过 5MB 不渲染 img，直接提示文件过大', () => {
    render(<ImagePreview path="assets/huge.png" {...BASE} size={6 * 1024 * 1024} />)
    expect(screen.queryByRole('img')).not.toBeInTheDocument()
    expect(screen.getByText(/文件过大（6\.0 MB）/)).toBeInTheDocument()
    expect(screen.getByRole('link', { name: '去 GitHub 查看 ↗' })).toBeInTheDocument()
  })
})
