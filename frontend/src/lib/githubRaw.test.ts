// src/lib/githubRaw.test.ts
import { describe, expect, it } from 'vitest'
import { blobUrl, encodePath, rawUrlFor } from './githubRaw'

describe('githubRaw', () => {
  it('encodePath 分段编码中文与空格', () => {
    expect(encodePath('assets/演示 截图.png')).toBe('assets/%E6%BC%94%E7%A4%BA%20%E6%88%AA%E5%9B%BE.png')
  })

  it('rawUrlFor 拼出 raw 直链', () => {
    expect(rawUrlFor('owner/repo', 'main', 'a b/c.png'))
      .toBe('https://raw.githubusercontent.com/owner/repo/main/a%20b/c.png')
  })

  it('blobUrl 拼出 GitHub 浏览深链并容忍仓库地址尾斜杠', () => {
    expect(blobUrl('https://github.com/owner/repo/', 'main', 'src/主 程序.py'))
      .toBe('https://github.com/owner/repo/blob/main/src/%E4%B8%BB%20%E7%A8%8B%E5%BA%8F.py')
  })

  // remark/react-markdown 会把链接 href 预编码，encodePath 必须幂等，否则二次转义（% → %25）
  it('encodePath 对已编码路径幂等（markdown 预编码场景）', () => {
    const encoded = 'docs/%E4%BD%BF%E7%94%A8%E8%AF%B4%E6%98%8E.md'
    expect(encodePath(encoded)).toBe(encoded)
  })

  it('encodePath 容忍非法转义序列（字面量 %）', () => {
    expect(encodePath('折扣100%.png')).toBe('%E6%8A%98%E6%89%A3100%25.png')
  })
})
