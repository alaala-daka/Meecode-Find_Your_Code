// src/components/FilterChips.tsx —— 已选筛选条件行：单条 ✕ 移除（即生效）、一键清除全部（spec §3.3）
import { useSearchParams } from 'react-router-dom'
import {
  activeFilterCount, describeFilters, parseFilters, removeFilter, writeFilters,
} from '../lib/repoFilters'
import './FilterChips.css'

interface Props {
  total?: number   // 「共 N 个仓库」；不传则不显示计数（搜索页已有总数文案）
}

export default function FilterChips({ total }: Props) {
  const [params, setParams] = useSearchParams()
  const filters = parseFilters(params)
  if (activeFilterCount(filters) === 0) return null

  function apply(next: typeof filters) {
    const p = new URLSearchParams(params)
    writeFilters(p, next)   // 内部已重置 page
    setParams(p)
  }

  return (
    <div className="filter-chips" role="group" aria-label="已选筛选条件">
      {describeFilters(filters).map((c) => (
        <button
          key={c.key}
          type="button"
          className="filter-chip is-active"
          aria-label={c.aria}
          onClick={() => apply(removeFilter(filters, c.key))}
        >
          {c.label} <span className="filter-chip-x" aria-hidden="true">✕</span>
        </button>
      ))}
      <button type="button" className="filter-chips-clear" onClick={() => apply({})}>
        清除全部
      </button>
      {total !== undefined && <span className="filter-chips-total">共 {total} 个仓库</span>}
    </div>
  )
}
