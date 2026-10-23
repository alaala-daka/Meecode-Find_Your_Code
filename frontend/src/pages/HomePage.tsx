// src/pages/HomePage.tsx —— 「全部/分类」仓库流：分类胶囊 + 线框卡片网格 + 无限滚动
import { useEffect, useRef } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import CategoryBar from '../components/CategoryBar'
import EmptyState from '../components/EmptyState'
import ErrorBanner from '../components/ErrorBanner'
import RepoCard from '../components/RepoCard'
import { SkeletonGrid } from '../components/Skeleton'
import TopBar from '../components/TopBar'
import { activeFilterCount, filterKey as makeFilterKey, parseFilters, writeFilters } from '../lib/repoFilters'
import { useFeedStore } from '../store/feedStore'
import './HomePage.css'

export default function HomePage() {
  const { cards, loading, error, hasMore, load, loadMore } = useFeedStore()
  const sentinelRef = useRef<HTMLDivElement>(null)
  const navigate = useNavigate()
  const [params, setParams] = useSearchParams()
  const cat = params.get('cat')
  const filters = parseFilters(params)
  const fkey = makeFilterKey(filters)
  const filterCount = activeFilterCount(filters)

  useEffect(() => {
    const s = useFeedStore.getState()
    // 首次加载，或 URL 分类/过滤与 store 不一致时重载（fkey 已把过滤变化纳入依赖，闭包里的 filters 与本次渲染同源）
    if (s.page === 0 || s.category !== cat || s.filterKey !== fkey) void load(cat, filters)
  }, [cat, fkey, load])

  useEffect(() => {
    const el = sentinelRef.current
    if (!el) return
    const observer = new IntersectionObserver(
      (entries) => {
        if (entries.some((e) => e.isIntersecting)) void loadMore()
      },
      { rootMargin: '400px' },
    )
    observer.observe(el)
    return () => observer.disconnect()
  }, [loadMore, cards.length, hasMore])

  const showEmpty = !loading && !error && cards.length === 0 && !hasMore
  const showSentinel = hasMore && cards.length > 0

  return (
    <>
      <TopBar />
      <CategoryBar />
      <h1 className="visually-hidden">觅码 · 发现潜力开源仓库</h1>
      <main id="main" className="page-shell">
        {error && (
          <ErrorBanner
            message="加载失败，请重试"
            onRetry={() => void load(useFeedStore.getState().category, useFeedStore.getState().filters)}
          />
        )}
        {cards.length === 0 && loading && <SkeletonGrid count={10} />}
        {showEmpty && filterCount > 0 && (
          <EmptyState
            title="没有符合条件的仓库"
            actionLabel="清除筛选"
            onAction={() => {
              const p = new URLSearchParams(params)
              writeFilters(p, {})
              setParams(p)
            }}
          />
        )}
        {showEmpty && filterCount === 0 && (
          <EmptyState title="这个分类还没有仓库" actionLabel="推广我的仓库" onAction={() => navigate('/submit')} />
        )}
        {cards.length > 0 && (
          <>
            <div className="repo-grid feed-enter">
              {cards.map((c) => <RepoCard key={c.id} data={c} />)}
            </div>
            {showSentinel && <div ref={sentinelRef} className="feed-sentinel" aria-hidden="true" />}
            {loading && cards.length > 0 && <SkeletonGrid count={4} />}
          </>
        )}
      </main>
    </>
  )
}
