export default function App() {
  return (
    <main className="min-h-screen bg-paper text-ink">
      <section className="mx-auto max-w-[1280px] px-6 py-10">
        <h1 className="font-mono text-2xl">Meecode 管理台</h1>
        <p className="mt-2 text-ink-2">脚手架就绪 · 纸面墨线令牌已接入</p>
        <div className="mt-6 rounded-lg border border-line bg-surface p-4 transition-[color,box-shadow] duration-[180ms] hover:shadow-hover">
          <span className="text-ink-3">token probe</span>
          <div className="mt-2 flex gap-2">
            <span className="rounded-sm bg-brand px-2 py-1 text-surface">brand</span>
            <span className="rounded-sm bg-tint px-2 py-1 text-ink-2">tint</span>
            <span className="rounded-sm border border-line-strong px-2 py-1 text-ink-3">
              line-strong
            </span>
          </div>
        </div>
      </section>
    </main>
  )
}
