import { describe, expect, it } from 'vitest'

import {
  UNCATEGORIZED_KEY,
  buildGroupedSubscriptions,
  buildSubscriptionOrderState,
  categoryOrderToPersistedIds,
  getCategoryMeta,
  getSubscriptionCategoryKey,
  moveCategoryByOffset,
  moveCategoryToTarget,
  moveValueByOffset,
  moveValueToTarget
} from './subscriptionOrdering'

const categories = [
  { id: 1, name: 'AI', icon: '🤖', sort: 20 },
  { id: 2, name: 'Streaming', icon: '🎬', sort: 10 },
  { id: 3, name: 'VPS', icon: '', sort: 20 }
]

const subscriptions = [
  { id: 30, category_id: 1, sort: 2, name: 'Claude' },
  { id: 10, category_id: 2, sort: 2, name: 'Netflix' },
  { id: 20, category_id: 1, sort: 1, name: 'OpenAI' },
  { id: 40, category_id: null, sort: 1, name: 'Uncategorized' },
  { id: 50, category_id: 3, sort: 1, name: 'Server' }
]

describe('getSubscriptionCategoryKey', () => {
  it('maps null or missing categories to the uncategorized key', () => {
    expect(getSubscriptionCategoryKey({ category_id: null })).toBe(UNCATEGORIZED_KEY)
    expect(getSubscriptionCategoryKey({})).toBe(UNCATEGORIZED_KEY)
  })

  it('converts real category ids to strings', () => {
    expect(getSubscriptionCategoryKey({ category_id: 12 })).toBe('12')
    expect(getSubscriptionCategoryKey({ category_id: 0 })).toBe('0')
  })
})

describe('getCategoryMeta', () => {
  it('returns the configured uncategorized label', () => {
    expect(getCategoryMeta(UNCATEGORIZED_KEY, categories, { uncategorizedName: '未分类' })).toEqual({ icon: '🗂️', name: '未分类' })
  })

  it('returns existing category metadata and icon fallback', () => {
    expect(getCategoryMeta('1', categories)).toEqual({ icon: '🤖', name: 'AI' })
    expect(getCategoryMeta('3', categories)).toEqual({ icon: '📁', name: 'VPS' })
  })

  it('falls back to the key for missing categories', () => {
    expect(getCategoryMeta('9', categories)).toEqual({ icon: '📁', name: '9' })
  })
})

describe('buildSubscriptionOrderState', () => {
  it('groups subscriptions, sorts items and honors saved category order', () => {
    expect(buildSubscriptionOrderState(subscriptions, categories, [1, 9, 1])).toEqual({
      orderMap: {
        '1': [20, 30],
        '2': [10],
        '3': [50],
        none: [40]
      },
      catOrder: ['1', '2', '3', 'none']
    })
  })

  it('orders unsaved categories by category sort and numeric id, with uncategorized last', () => {
    expect(buildSubscriptionOrderState(subscriptions, categories, []).catOrder).toEqual(['2', '1', '3', 'none'])
  })

  it('does not mutate input subscriptions', () => {
    const input = [{ id: 2, category_id: 1, sort: 2 }, { id: 1, category_id: 1, sort: 1 }]
    buildSubscriptionOrderState(input, categories, [])

    expect(input.map((x) => x.id)).toEqual([2, 1])
  })
})

describe('buildGroupedSubscriptions', () => {
  it('builds display groups from order state', () => {
    const groups = buildGroupedSubscriptions(subscriptions, {
      '2': [10, 999],
      none: [40],
      empty: []
    }, ['2', 'empty', 'none'], categories, { uncategorizedName: '未分类' })

    expect(groups).toEqual([
      { key: '2', icon: '🎬', name: 'Streaming', items: [subscriptions[1]] },
      { key: 'none', icon: '🗂️', name: '未分类', items: [subscriptions[3]] }
    ])
  })
})

describe('moveValueByOffset', () => {
  it('moves values by offset without mutating the input', () => {
    const list = [1, 2, 3]
    const next = moveValueByOffset(list, 2, -1)

    expect(next).toEqual([2, 1, 3])
    expect(list).toEqual([1, 2, 3])
  })

  it('returns the original list when movement is impossible', () => {
    const list = [1, 2, 3]

    expect(moveValueByOffset(list, 1, -1)).toBe(list)
    expect(moveValueByOffset(list, 3, 1)).toBe(list)
    expect(moveValueByOffset(list, 9, 1)).toBe(list)
  })
})

describe('moveValueToTarget', () => {
  it('keeps the current drop semantics when moving toward the front', () => {
    expect(moveValueToTarget([1, 2, 3, 4], 4, 2)).toEqual([1, 4, 2, 3])
  })

  it('keeps the current drop semantics when moving toward the back', () => {
    expect(moveValueToTarget([1, 2, 3, 4], 2, 4)).toEqual([1, 3, 4, 2])
  })

  it('returns the original list when movement is invalid', () => {
    const list = [1, 2, 3]

    expect(moveValueToTarget(list, 2, 2)).toBe(list)
    expect(moveValueToTarget(list, 9, 2)).toBe(list)
    expect(moveValueToTarget(list, 2, 9)).toBe(list)
  })
})

describe('category movement helpers', () => {
  it('moves only real categories and keeps uncategorized pinned last', () => {
    expect(moveCategoryByOffset(['1', '2', 'none'], '1', 1)).toEqual(['2', '1', 'none'])
    expect(moveCategoryToTarget(['1', '2', '3', 'none'], '1', '3')).toEqual(['2', '3', '1', 'none'])
  })

  it('returns the original list when moving uncategorized or targeting it', () => {
    const list = ['1', '2', 'none']

    expect(moveCategoryByOffset(list, 'none', -1)).toBe(list)
    expect(moveCategoryByOffset(list, '2', 1)).toBe(list)
    expect(moveCategoryToTarget(list, 'none', '1')).toBe(list)
    expect(moveCategoryToTarget(list, '1', 'none')).toBe(list)
  })
})

describe('categoryOrderToPersistedIds', () => {
  it('removes uncategorized and converts keys to numbers', () => {
    expect(categoryOrderToPersistedIds(['2', 'none', '3'])).toEqual([2, 3])
  })
})
