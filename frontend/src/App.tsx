// src/App.tsx
import { useEffect } from 'react'
import { Routes, Route, Navigate, useLocation } from 'react-router-dom'
import HomePage from './pages/HomePage'
import ProfilePage from './pages/ProfilePage'
import RepoPage from './pages/RepoPage'
import SearchPage from './pages/SearchPage'
import SubmitPage from './pages/SubmitPage'
import SiteFooter from './components/SiteFooter'
import { useAuthStore } from './store/authStore'
import { sendPageView } from './lib/beacon'
import './App.css'

export default function App() {
  const location = useLocation()
  // 挂载时做一次会话引导（GET /api/me 恢复登录态）：
  // 幂等，StrictMode 双调用无害；引导失败按未登录处理，不打断渲染
  useEffect(() => {
    useAuthStore.getState().bootstrap().catch(() => {})
  }, [])

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
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
      <SiteFooter />
    </div>
  )
}
