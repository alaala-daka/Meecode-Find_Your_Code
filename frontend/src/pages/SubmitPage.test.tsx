// src/pages/SubmitPage.test.tsx
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { FIXTURE_USER } from '../api/fixtures'
import { useAuthStore } from '../store/authStore'
import SubmitPage from './SubmitPage'

function renderPage() {
  return render(
    <MemoryRouter initialEntries={['/submit']}>
      <Routes>
        <Route path="/submit" element={<SubmitPage />} />
      </Routes>
    </MemoryRouter>
  )
}

describe('SubmitPage', () => {
  beforeEach(() => useAuthStore.setState({ user: null }))

  it('未登录显示登录引导', () => {
    renderPage()
    expect(screen.getByText('用 GitHub 登录后即可推广你的仓库')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: '用 GitHub 登录' })).toBeInTheDocument()
  })

  it('步1 列出我的仓库并可勾选', async () => {
    useAuthStore.setState({ user: FIXTURE_USER })
    renderPage()
    const repo = await screen.findByText('mini-agent')
    expect(repo).toBeInTheDocument()
    await userEvent.click(screen.getByLabelText(/mini-agent/))
    expect(screen.getByRole('button', { name: '下一步' })).toBeEnabled()
  })

  it('步2 卖点必填校验与 AI 草稿', async () => {
    useAuthStore.setState({ user: FIXTURE_USER })
    renderPage()
    await userEvent.click(await screen.findByLabelText(/mini-agent/))
    await userEvent.click(screen.getByRole('button', { name: '下一步' }))
    const next = screen.getByRole('button', { name: '发布' })
    expect(next).toBeDisabled()
    await userEvent.click(screen.getByRole('button', { name: 'AI 帮我写' }))
    expect(await screen.findByDisplayValue(/最小运行时/)).toBeInTheDocument()
    expect(next).toBeEnabled()
  })

  it('步2 卡片预览是静态卡：无链接、不参与跳转', async () => {
    useAuthStore.setState({ user: FIXTURE_USER })
    renderPage()
    await userEvent.click((await screen.findAllByLabelText(/mini-agent/))[0])
    await userEvent.click(screen.getByRole('button', { name: '下一步' }))
    const preview = screen.getByText('卡片预览').parentElement as HTMLElement
    expect(preview.querySelector('.repo-card')).toHaveClass('repo-card--static')
    expect(preview.querySelectorAll('a')).toHaveLength(0)
  })

  it('步3 发布成功', async () => {
    useAuthStore.setState({ user: FIXTURE_USER })
    renderPage()
    await userEvent.click(await screen.findByLabelText(/mini-agent/))
    await userEvent.click(screen.getByRole('button', { name: '下一步' }))
    await userEvent.type(screen.getByLabelText('一句话卖点'), '手写的一句话卖点')
    await userEvent.click(screen.getByRole('button', { name: '发布' }))
    expect(await screen.findByText('已发布，进入首发曝光窗口')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: '查看我的主页' })).toBeInTheDocument()
  })

  it('AI 生成失败提示且不阻塞手写', async () => {
    useAuthStore.setState({ user: FIXTURE_USER })
    const { api } = await import('../api/client')
    const spy = vi.spyOn(api, 'aiDraft').mockRejectedValueOnce(new Error('boom'))
    renderPage()
    // 前序用例发布过同名仓库（mock 状态共享），存在多个 mini-agent 输入
    await userEvent.click((await screen.findAllByLabelText(/mini-agent/))[0])
    await userEvent.click(screen.getByRole('button', { name: '下一步' }))
    await userEvent.click(screen.getByRole('button', { name: 'AI 帮我写' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('AI 生成失败')
    expect(screen.getByRole('button', { name: 'AI 帮我写' })).toBeEnabled()
    spy.mockRestore()
  })

  it('发布失败显示提示且按钮恢复', async () => {
    useAuthStore.setState({ user: FIXTURE_USER })
    const { api } = await import('../api/client')
    const spy = vi.spyOn(api, 'submitRepo').mockRejectedValueOnce(new Error('boom'))
    renderPage()
    await userEvent.click((await screen.findAllByLabelText(/mini-agent/))[0])
    await userEvent.click(screen.getByRole('button', { name: '下一步' }))
    await userEvent.type(screen.getByLabelText('一句话卖点'), '手写卖点')
    await userEvent.click(screen.getByRole('button', { name: '发布' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('发布失败')
    expect(screen.getByRole('button', { name: '发布' })).toBeEnabled()
    spy.mockRestore()
  })

  it('卖点字数计数实时更新', async () => {
    useAuthStore.setState({ user: FIXTURE_USER })
    renderPage()
    await userEvent.click((await screen.findAllByLabelText(/mini-agent/))[0])
    await userEvent.click(screen.getByRole('button', { name: '下一步' }))
    const input = screen.getByLabelText('一句话卖点')
    await userEvent.type(input, 'abcde')
    expect(screen.getByText(/5\/40/)).toBeInTheDocument()
  })

  it('AI 草稿后自动选中推荐分类并带角标', async () => {
    useAuthStore.setState({ user: FIXTURE_USER })
    renderPage()
    await userEvent.click((await screen.findAllByLabelText(/mini-agent/))[0])
    await userEvent.click(screen.getByRole('button', { name: '下一步' }))
    await userEvent.click(screen.getByRole('button', { name: 'AI 帮我写' }))
    // mini-agent → 推荐并自动选中「AI 与机器学习」，胶囊上出现 AI 角标
    await screen.findByText('AI')
    expect(screen.getByRole('button', { name: /AI 与机器学习/ })).toHaveAttribute('aria-pressed', 'true')
  })

  it('「其他」替换为可输入的自定义分类', async () => {
    useAuthStore.setState({ user: FIXTURE_USER })
    renderPage()
    await userEvent.click((await screen.findAllByLabelText(/mini-agent/))[0])
    await userEvent.click(screen.getByRole('button', { name: '下一步' }))
    expect(screen.queryByRole('button', { name: '其他' })).not.toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: '自定义' }))
    // 用不在后端 8 类中的词验证「任意自定义分类」
    await userEvent.type(screen.getByLabelText('自定义分类'), '硬件创客')
    expect(screen.getByRole('button', { name: '硬件创客' })).toHaveAttribute('aria-pressed', 'true')
    await userEvent.type(screen.getByLabelText('一句话卖点'), '手写卖点')
    await userEvent.click(screen.getByRole('button', { name: '发布' }))
    // 自定义分类可随发布正常提交
    expect(await screen.findByText('已发布，进入首发曝光窗口')).toBeInTheDocument()
  })
})
