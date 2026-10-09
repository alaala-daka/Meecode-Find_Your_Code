// 页面访问 beacon（spec 2026-10-09 §2.3）：同 path 2 秒去重防 StrictMode 双计；埋点失败静默
// 安全复审修订（2026-10-09）：sendBeacon 传字符串 body 会按 text/plain 发送，
// FastAPI 的 Pydantic body 只收 JSON（实测 422）——必须用 Blob 带 application/json。
const DEDUPE_MS = 2000
let lastPath = ''
let lastAt = 0

export function sendPageView(path: string): void {
  try {
    const now = Date.now()
    if (path === lastPath && now - lastAt < DEDUPE_MS) return
    lastPath = path
    lastAt = now
    const body = JSON.stringify({ path })
    if (typeof navigator.sendBeacon === 'function') {
      navigator.sendBeacon('/api/hit', new Blob([body], { type: 'application/json' }))
      return
    }
    void fetch('/api/hit', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body,
      keepalive: true,
    }).catch(() => {})
  } catch {
    /* 埋点失败静默 */
  }
}
