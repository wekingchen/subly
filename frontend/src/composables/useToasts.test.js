import { describe, expect, it, vi } from 'vitest'
import { useToasts } from './useToasts'

describe('useToasts', () => {
  it('keeps existing toast types and removes each toast independently', () => {
    vi.useFakeTimers()
    try {
      const { toasts, add, remove } = useToasts({ duration: 1000 })
      const first = add('已保存')
      add('请求失败', 'err')

      expect(toasts.value).toEqual([
        { id: first, message: '已保存', type: 'ok' },
        { id: first + 1, message: '请求失败', type: 'err' }
      ])

      remove(first)
      expect(toasts.value).toHaveLength(1)
      vi.advanceTimersByTime(1000)
      expect(toasts.value).toEqual([])
    } finally {
      vi.useRealTimers()
    }
  })
})
