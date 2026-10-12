// src/App.tsx
import { useEffect } from 'react'
import { Routes, Route, Navigate, useLocation } from 'react-router-dom'
import FeedbackDetailPage from './pages/FeedbackDetailPage'
import HomePage from './pages/HomePage'
import MyFeedbackPage from './pages/MyFeedbackPage'
import ProfilePage from './pages/ProfilePage'
import RepoPage from './pages/RepoPage'
import SearchPage from './pages/SearchPage'
import SubmitPage from './pages/SubmitPage'
import SiteFooter from './components/SiteFooter'
import { useAuthStore } from './store/authStore'
import { POLL_MS, useNotificationStore } from './store/notificationStore'
import { sendPageView } from './lib/beacon'
import './App.css'

export default function App() {
  const location = useLocation()
  const user = useAuthStore((s) => s.user)
  // 挂载时做一次会话引导（GET /api/me 恢复登录态）：
  // 幂等，StrictMode 双调用无害；引导失败按未登录处理，不打断渲染
  useEffect(() => {
    useAuthStore.getState().bootstrap().catch(() => {})
  }, [])

  // 管理回复未读数：登录态下 60s 轮询一次（组件只消费计数，不各自起定时器）
  useEffect(() => {
    if (!user) { useNotificationStore.setState({ count: 0 }); return }  // 登出即清零，防红点残留
    const refresh = useNotificationStore.getState().refresh
    void refresh()
    const timer = setInterval(() => void refresh(), POLL_MS)
    return () => clearInterval(timer)
  }, [user])

  useEffect(() => {
    sendPageView(location.pathname)
  }, [location.pathname])

  return (
    <div id="app-root">
      <a className="skip-link" href="#main">跳转到主要内容</a>
      <Routes>
        <Route path="/" element={<HomePage />} />
        <Route path="/search" element={<SearchPage />} />
        <Route path="/repo/:id" element={<RepoPage />} />
        <Route path="/submit" element={<SubmitPage />} />
        <Route path="/user/:login" element={<ProfilePage />} />
        <Route path="/my/feedback" element={<MyFeedbackPage />} />
        <Route path="/my/feedback/:id" element={<FeedbackDetailPage />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
      <SiteFooter />
    </div>
  )
}
