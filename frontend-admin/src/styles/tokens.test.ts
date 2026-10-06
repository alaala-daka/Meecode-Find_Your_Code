// @vitest-environment node
// 本文件读取真实文件系统（jsdom 环境下 new URL(rel, import.meta.url) 会解析到文档基址，故固定 node）
import { existsSync, readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { describe, expect, it } from 'vitest'
import tailwindConfig from '../../tailwind.config'

const read = (url: string) => readFileSync(fileURLToPath(new URL(url, import.meta.url)), 'utf8')

const tokensCss = read('./tokens.css')
const themeCssPath = fileURLToPath(new URL('../../../frontend/src/styles/theme.css', import.meta.url))

describe('主题令牌', () => {
  it('tokens.css 含纸面墨线关键令牌', () => {
    expect(tokensCss).toContain('--paper: #FAF9F6;')
    expect(tokensCss).toContain('--surface: #FFFFFF;')
    expect(tokensCss).toContain('--brand: #AE5139;')
    expect(tokensCss).toContain('--line: #E7E3D8;')
    expect(tokensCss).toContain('--radius-sm: 6px;')
    expect(tokensCss).toContain('--time-fast: 0.18s;')
  })

  it('tokens.css 与主站 theme.css 的 :root 块一致', () => {
    if (!existsSync(themeCssPath)) return
    const rootBlock = (css: string) => css.slice(css.indexOf(':root {'))
    expect(rootBlock(tokensCss).trim()).toBe(rootBlock(readFileSync(themeCssPath, 'utf8')).trim())
  })

  it('tailwind 色板映射到 CSS 变量', () => {
    const colors = tailwindConfig.theme.extend.colors as Record<string, unknown>
    expect(colors.paper).toBe('var(--paper)')
    expect(colors.ink).toBe('var(--ink)')
    expect((colors.brand as Record<string, string>).DEFAULT).toBe('var(--brand)')
    expect((colors.line as Record<string, string>).DEFAULT).toBe('var(--line)')
    expect(colors.danger).toBe('var(--danger)')
  })
})
