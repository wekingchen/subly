import { describe, expect, it } from 'vitest'
import { categoryColor, categoryVisualKey, UNCATEGORIZED_COLOR } from './categoryVisual'

describe('categoryVisual', () => {
  it('优先使用分类持久颜色', () => {
    expect(categoryColor({ category_id: 3, category_color: '#123456' })).toBe('#123456')
  })

  it('同一分类 ID 始终产生相同 fallback，且不受排名影响', () => {
    const first = categoryColor({ category_id: 42 })
    expect(categoryColor({ category_id: 42 })).toBe(first)
    expect(categoryColor({ category_id: 43 })).not.toBe(first)
  })

  it('未分类使用固定中性色和稳定 key', () => {
    expect(categoryColor({ category_id: null })).toBe(UNCATEGORIZED_COLOR)
    expect(categoryVisualKey({ category_id: null })).toBe('uncategorized')
    expect(categoryVisualKey({ category_id: 7 })).toBe('7')
  })
})
