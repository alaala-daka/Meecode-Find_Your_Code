// src/lib/githubRaw.test.ts
import { describe, expect, it } from 'vitest'
import { blobUrl, decodePath, encodePath, rawUrlFor } from './githubRaw'

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

  // encodePath 是纯编码：字面转义序列按字面量处理（文件真名 'a%20b.png' ≠ 'a b.png'）
  it('encodePath 纯语义：字面 %20 不解读，编码为 %2520', () => {
    expect(encodePath('a%20b.png')).toBe('a%2520b.png')
  })

  // react-markdown 会把 markdown 链接 href 预编码；归一由 decodePath 在 ReadmeSection 边界做
  it('decodePath 归一：预编码解码回字面量，非法转义回退原段', () => {
    expect(decodePath('docs/%E4%BD%BF%E7%94%A8%E8%AF%B4%E6%98%8E.md')).toBe('docs/使用说明.md')
    expect(decodePath('a%20b%.png')).toBe('a%20b%.png')
  })
})
