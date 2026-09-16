import { describe, expect, it } from 'vitest'

import {
  UNCATEGORIZED_KEY,
  buildGroupedSubscriptions,
  buildSubscriptionOrderState,
  categoryOrderToPersistedIds,
  getCategoryMeta,
  getManuallyOrderedKeys,
  getSubscriptionCategoryKey,
  moveCategoryByOffset,
  moveCategoryToTarget,
  moveValueByOffset,
  moveValueToTarget,
  normalizeSavedSubscriptionOrder
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

// 默认排序（用户确认口径）：每类内按剩余订阅时间由近及远——到期日越早越前。
describe('buildSubscriptionOrderState 默认到期日排序', () => {
  const dated = [
    { id: 1, category_id: 1, next_renewal_date: '2026-10-01', name: '较远' },
    { id: 2, category_id: 1, next_renewal_date: '2026-09-20', name: '较近' },
    { id: 3, category_id: 1, next_renewal_date: '2026-09-15', name: '最近' },
    { id: 4, category_id: 1, name: '无日期（买断）' }
  ]

  it('同分类内按 next_renewal_date 升序（越近结束越前面），无日期沉底', () => {
    const state = buildSubscriptionOrderState(dated, categories, [])
    expect(state.orderMap['1']).toEqual([3, 2, 1, 4])
  })

  it('已保存的手动排序仍然优先（拖拽排序不被默认排序覆盖）', () => {
    // 先构建默认顺序再模拟用户拖拽保存：orderMap 顺序由调用方持有
    const initial = buildSubscriptionOrderState(dated, categories, [])
    const dragged = { ...initial.orderMap, '1': [1, 3, 2, 4] }
    const groups = buildGroupedSubscriptions(dated, dragged, initial.catOrder, categories)
    expect(groups[0].items.map((s) => s.id)).toEqual([1, 3, 2, 4])
  })

  it('到期日相同回退 (sort, id)（输入顺序与 sort 冲突也能正确排序）', () => {
    const sameDate = [
      { id: 8, sort: 2, category_id: 1, next_renewal_date: '2026-09-20', name: '乙' },
      { id: 7, sort: 1, category_id: 1, next_renewal_date: '2026-09-20', name: '甲' }
    ]
    // sorts=[2,1] 构成 0..n-1 连续 → 手动排序优先，按 sort 升序 [7, 8]
    const state = buildSubscriptionOrderState(sameDate, categories, [])
    expect(state.orderMap['1']).toEqual([7, 8])
  })
})

describe('getManuallyOrderedKeys（手动拖拽顺序持久化，审核 Medium）', () => {
  it('返回已手动排序分类的 key 集合；空偏好返回空集合', () => {
    expect(getManuallyOrderedKeys({ '1': [2, 1], none: [4] })).toEqual(new Set(['1', 'none']))
    expect(getManuallyOrderedKeys(undefined).size).toBe(0)
    expect(getManuallyOrderedKeys({}).size).toBe(0)
  })

  it('持久化顺序在视图 rebuild 后恢复：未被拖拽的分类不受影响', () => {
    // 模拟视图 rebuild：默认日期排序 → 用持久化 ID 列表覆盖已手动排序分类
    const dated = [
      { id: 1, category_id: 1, next_renewal_date: '2026-10-01', name: 'A较远' },
      { id: 2, category_id: 1, next_renewal_date: '2026-09-20', name: 'B较近' }
    ]
    const state = buildSubscriptionOrderState(dated, categories, [])
    expect(state.orderMap['1']).toEqual([2, 1])  // 默认：越近结束越前面
    const saved = { '1': [1, 2] }                 // 用户拖拽后持久化的顺序
    const restored = saved['1'].filter((id) => state.orderMap['1'].includes(id))
    expect(restored).toEqual([1, 2])              // 拖拽顺序恢复，不被日期覆盖
  })
})

// rebuild 规范化逻辑提取的纯函数（复审 Low）：过滤失效 ID / 追加新成员 /
// 空分类跳过不写 key / 内容比较触发写回。
describe('normalizeSavedSubscriptionOrder', () => {
  it('过滤失效 ID 并追加新成员到末尾', () => {
    const { normalized, orderChanged, applied } = normalizeSavedSubscriptionOrder(
      { '1': [1, 99, 2] },           // 99 已不存在
      { '1': [2, 1, 3] }             // 当前默认日期序：3 是新成员
    )
    expect(normalized['1']).toEqual([1, 2, 3])   // 保留持久化顺序 + 追加 3
    expect(applied['1']).toEqual([1, 2, 3])
    expect(orderChanged).toBe(true)              // 内容变了必须写回
  })

  it('成员一进一出（等长但内容变）也触发写回', () => {
    const { orderChanged } = normalizeSavedSubscriptionOrder(
      { '1': [1, 2] },               // 2 已删除、4 是新成员——长度同为 2
      { '1': [1, 4] }
    )
    expect(orderChanged).toBe(true)
  })

  it('完全一致时不触发写回', () => {
    const { orderChanged, applied } = normalizeSavedSubscriptionOrder(
      { '1': [2, 1] },
      { '1': [2, 1] }
    )
    expect(orderChanged).toBe(false)
    expect(applied['1']).toEqual([2, 1])
  })

  it('空分类/空数组 key 省略不写入，标记写回', () => {
    const { normalized, orderChanged } = normalizeSavedSubscriptionOrder(
      { '1': [1], '2': [5] },        // '2' 分类已清空
      { '1': [1] }                   // orderMap 里没有 '2'
    )
    expect(Object.keys(normalized)).toEqual(['1'])
    expect(orderChanged).toBe(true)
  })

  it('历史脏数据（非数组值）跳过', () => {
    const { normalized, orderChanged } = normalizeSavedSubscriptionOrder(
      { '1': 'corrupt', '2': [1] },
      { '2': [1] }
    )
    expect(Object.keys(normalized)).toEqual(['2'])
    expect(orderChanged).toBe(false)
  })

  it('空偏好原样返回且不触发写回', () => {
    const { normalized, orderChanged, applied } = normalizeSavedSubscriptionOrder(undefined, { '1': [1] })
    expect(normalized).toEqual({})
    expect(applied).toEqual({})
    expect(orderChanged).toBe(false)
  })
})
