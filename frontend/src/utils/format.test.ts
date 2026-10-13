// src/utils/format.test.ts
import { describe, expect, it } from 'vitest'
import { formatCount, formatEpoch, formatTime } from './format'

const NOW = Date.UTC(2026, 7, 25, 12, 0, 0)

describe('formatTime', () => {
  it('一小时内「刚刚」', () => {
    expect(formatTime(new Date(NOW - 30 * 60_000).toISOString(), NOW)).toBe('刚刚')
  })
  it('小时与天', () => {
    expect(formatTime(new Date(NOW - 5 * 3600_000).toISOString(), NOW)).toBe('5 小时前')
    expect(formatTime(new Date(NOW - 3 * 86400_000).toISOString(), NOW)).toBe('3 天前')
  })
  it('超 7 天显示 MM-DD', () => {
    expect(formatTime(new Date(NOW - 30 * 86400_000).toISOString(), NOW)).toBe('07-26')
  })
})

describe('formatCount', () => {
  it('万位缩写', () => {
    expect(formatCount(3100)).toBe('3100')
    expect(formatCount(31000)).toBe('3.1万')
    expect(formatCount(20000)).toBe('2万')
  })
})

it('formatEpoch 把 epoch 秒转相对时间', () => {
  const now = Date.UTC(2026, 9, 12, 12, 0, 0)
  expect(formatEpoch(Math.floor((now - 3 * 3600 * 1000) / 1000), now)).toBe('3 小时前')
})
