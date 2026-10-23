// src/components/CodeView.test.tsx —— 代码预览：逐行行号 + 超长截断 + 长行横向滚动样式契约
import { readFileSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'
import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import type { RepoFile } from '../api/types'
import CodeView from './CodeView'

const codeViewCss = readFileSync(join(dirname(fileURLToPath(import.meta.url)), 'CodeView.css'), 'utf8')

function makeFile(content: string, path = 'src/loop.py'): RepoFile {
  return { path, content }
}

describe('CodeView', () => {
  it('逐行渲染行号与代码文本（空行保留占位）', () => {
    render(<CodeView file={makeFile('first line\n\nthird line')} githubUrl="https://github.com/a/b" />)
    const body = screen.getByTestId('code-content')
    expect(body).toHaveTextContent('first line')
    expect(body).toHaveTextContent('third line')
    expect(body.querySelectorAll('.code-ln')).toHaveLength(3)
  })

  it('超长文件只展示前 2000 行并给出截断提示', () => {
    const content = Array.from({ length: 2001 }, (_, i) => `line ${i + 1}`).join('\n')
    render(<CodeView file={makeFile(content)} githubUrl="https://github.com/a/b" />)
    const body = screen.getByTestId('code-content')
    expect(body.querySelectorAll('.code-line')).toHaveLength(2000)
    expect(screen.getByText(/仅展示前 2000 行/)).toBeInTheDocument()
  })

  it('样式契约：长行在 .code-body 内横向滚动（手机端右滑可看全行）', () => {
    // content-visibility: auto 自带绘制包含（paint containment）：溢出被裁在行盒内，
    // 既显示不全也不计入 .code-body 的横向滚动宽度，导致长行无法右滑查看。
    // 因此 .code-line 必须撑到文本宽度（fit-content/max-content），短行再用 min-width 铺满整行。
    expect(codeViewCss).toMatch(/\.code-line\s*\{[^}]*width:\s*(?:-webkit-)?(?:fit-content|max-content)/)
    expect(codeViewCss).toMatch(/\.code-line\s*\{[^}]*min-width:\s*100%/)
    expect(codeViewCss).toMatch(/\.code-body\s*\{[^}]*overflow-x:\s*auto/)
    expect(codeViewCss).toMatch(/\.code-text\s*\{[^}]*white-space:\s*pre/)
  })
})
