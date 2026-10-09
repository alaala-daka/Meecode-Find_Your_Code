import { afterEach, describe, expect, it, vi } from 'vitest'
import { sendPageView } from './beacon'

// jsdom 的 Blob 没有 .text()（Node 原生 Blob 才有）——用 FileReader 读回内容
function readBlobText(blob: Blob): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader()
    reader.onload = () => resolve(String(reader.result))
    reader.onerror = () => reject(reader.error ?? new Error('blob read failed'))
    reader.readAsText(blob)
  })
}

describe('sendPageView', () => {
  afterEach(() => {
    vi.restoreAllMocks()
    vi.useRealTimers()
  })

  it('sendBeacon 以 application/json Blob 上报 path', async () => {
    const sendBeacon = vi.fn().mockReturnValue(true)
    Object.defineProperty(navigator, 'sendBeacon', { value: sendBeacon, configurable: true })
    sendPageView('/search')
    expect(sendBeacon).toHaveBeenCalledTimes(1)
    expect(sendBeacon.mock.calls[0][0]).toBe('/api/hit')
    const payload = sendBeacon.mock.calls[0][1] as Blob
    expect(payload).toBeInstanceOf(Blob)
    expect(payload.type).toBe('application/json')
    expect(await readBlobText(payload)).toBe('{"path":"/search"}')
  })

  it('同 path 2 秒内去重', () => {
    const sendBeacon = vi.fn().mockReturnValue(true)
    Object.defineProperty(navigator, 'sendBeacon', { value: sendBeacon, configurable: true })
    sendPageView('/dedupe')
    sendPageView('/dedupe')
    expect(sendBeacon).toHaveBeenCalledTimes(1)
    vi.useFakeTimers()
    vi.setSystemTime(Date.now() + 3000)
    sendPageView('/dedupe')
    expect(sendBeacon).toHaveBeenCalledTimes(2)
    vi.useRealTimers()
  })

  it('无 sendBeacon 回落 fetch keepalive，失败静默', async () => {
    Object.defineProperty(navigator, 'sendBeacon', { value: undefined, configurable: true })
    const fetchSpy = vi.spyOn(globalThis, 'fetch').mockRejectedValue(new Error('net'))
    sendPageView('/repo/1') // 不抛
    await Promise.resolve()
    expect(fetchSpy).toHaveBeenCalledTimes(1)
    const [url, init] = fetchSpy.mock.calls[0]
    expect(String(url)).toBe('/api/hit')
    expect((init as RequestInit).keepalive).toBe(true)
  })
})
