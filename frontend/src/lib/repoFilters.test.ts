// src/lib/repoFilters.test.ts —— URL 参数白名单契约（spec §3.1）
import { describe, expect, it } from 'vitest'
import {
  activeFilterCount, describeFilters, filterKey, filterQuery,
  parseFilters, removeFilter, writeFilters,
} from './repoFilters'

describe('parseFilters', () => {
  it('解析五个参数，topic 取重复键', () => {
    const p = new URLSearchParams('lang=Python&stars=100&stars_max=500&since=30d&topic=llm&topic=self-hosted')
    expect(parseFilters(p)).toEqual({
      lang: 'Python', stars: 100, starsMax: 500, since: '30d', topics: ['llm', 'self-hosted'],
    })
  })

  it('非法值丢弃（后端才 422，前端宽容）', () => {
    const p = new URLSearchParams('lang=语言&stars=abc&stars_max=-1&since=2024&topic=话题')
    expect(parseFilters(p)).toEqual({})
    expect(parseFilters(new URLSearchParams('stars=500&stars_max=100'))).toEqual({}) // stars_max < stars 整体丢弃
  })

  it('白名单外参数不读', () => {
    expect(parseFilters(new URLSearchParams('foo=1&q=abc&cat=开发工具'))).toEqual({})
  })
})

describe('writeFilters', () => {
  it('只重写白名单参数并重置 page，其他参数保留', () => {
    const p = new URLSearchParams('q=abc&cat=开发工具&lang=Go&page=3')
    writeFilters(p, { stars: 100, topics: ['llm'] })
    expect(p.get('q')).toBe('abc')
    expect(p.get('cat')).toBe('开发工具')
    expect(p.get('stars')).toBe('100')
    expect(p.getAll('topic')).toEqual(['llm'])
    expect(p.get('lang')).toBeNull()
    expect(p.get('page')).toBeNull()
  })
})

describe('filterQuery / filterKey / 计数', () => {
  it('filterQuery 生成 API 查询串，topic 重复键', () => {
    const q = filterQuery({ lang: 'Python', stars: 100, topics: ['llm', 'cli'] })
    expect(q.get('lang')).toBe('Python')
    expect(q.get('stars')).toBe('100')
    expect(q.getAll('topic')).toEqual(['llm', 'cli'])
  })

  it('filterKey 稳定：同值同串、topics 顺序不敏感', () => {
    expect(filterKey({ lang: 'Go', topics: ['a', 'b'] })).toBe(filterKey({ lang: 'Go', topics: ['b', 'a'] }))
    expect(filterKey({})).not.toBe(filterKey({ lang: 'Go' }))
  })

  it('activeFilterCount：每个维度 1、topics 每个 1', () => {
    expect(activeFilterCount({})).toBe(0)
    expect(activeFilterCount({ lang: 'Go', stars: 10, since: '7d', topics: ['a', 'b'] })).toBe(5)
  })
})

describe('removeFilter / describeFilters', () => {
  const f = { lang: 'Python', stars: 100, starsMax: 500, since: '30d' as const, topics: ['llm', 'cli'] }

  it('按 chipKey 移除单条', () => {
    expect(removeFilter(f, 'lang')).toEqual({ stars: 100, starsMax: 500, since: '30d', topics: ['llm', 'cli'] })
    expect(removeFilter(f, 'topic:cli').topics).toEqual(['llm'])
    expect(removeFilter(f, 'starsMax')).not.toHaveProperty('starsMax')
  })

  it('describeFilters 生成 chips（含可访问名称）', () => {
    const chips = describeFilters(f)
    expect(chips.map((c) => c.key)).toEqual(['lang', 'stars', 'starsMax', 'since', 'topic:llm', 'topic:cli'])
    expect(chips[0]).toEqual({ key: 'lang', label: 'Python', aria: '移除语言筛选 Python' })
    expect(chips[1].label).toBe('★ ≥ 100')
    expect(chips[3].label).toBe('近一月')
  })
})
