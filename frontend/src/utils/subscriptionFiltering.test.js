import { describe, expect, it } from 'vitest'
import { filterSubscriptions, hasSubscriptionFilters } from './subscriptionFiltering'

const today = new Date(2026, 7, 13)
const items = [
  { id: 1, name: 'Netflix', plan: '家庭版', remark: '客厅电视', billing_type: 'recurring', next_renewal_date: '2026-08-10', is_active: true },
  { id: 2, name: 'Cloud VPS', plan: 'Pro', notes: '香港 CN2', billing_type: 'recurring', next_renewal_date: '2026-08-18', is_active: true },
  { id: 3, name: '永久授权', billing_type: 'one_time', start_date: '2026-08-01', is_active: true },
  { id: 4, name: '暂停订阅', billing_type: 'recurring', next_renewal_date: '2026-08-11', is_active: true, is_paused: true },
  { id: 5, name: '停用订阅', billing_type: 'recurring', next_renewal_date: '2026-08-11', is_active: false },
  { id: 6, name: '已经截止', billing_type: 'recurring', next_renewal_date: '2026-08-01', end_date: '2026-08-12', is_active: true },
  { id: 7, name: '截止日当天', billing_type: 'recurring', next_renewal_date: '2026-08-01', end_date: '2026-08-13', is_active: true }
]

describe('subscriptionFiltering', () => {
  it('搜索名称、套餐、备注和附加说明并忽略大小写与空白', () => {
    expect(filterSubscriptions(items, { query: ' netflix ' }).map((item) => item.id)).toEqual([1])
    expect(filterSubscriptions(items, { query: '家庭版' }).map((item) => item.id)).toEqual([1])
    expect(filterSubscriptions(items, { query: 'cn2' }).map((item) => item.id)).toEqual([2])
  })

  it('组合类型和风险筛选', () => {
    expect(filterSubscriptions(items, { type: 'one_time' }).map((item) => item.id)).toEqual([3])
    expect(filterSubscriptions(items, { type: 'recurring', risk: 'soon' }, { today }).map((item) => item.id)).toEqual([2])
    expect(filterSubscriptions(items, { risk: 'overdue' }, { today }).map((item) => item.id)).toEqual([1, 7])
  })

  it('暂停、停用、买断和结束日之前已截止的订阅不进入续费风险结果', () => {
    expect(filterSubscriptions(items, { risk: 'overdue' }, { today }).map((item) => item.id)).toEqual([1, 7])
    expect(filterSubscriptions(items, { query: '已经截止', risk: 'overdue' }, { today })).toEqual([])
  })

  it('不会修改输入并能判断任意筛选是否生效', () => {
    const snapshot = structuredClone(items)
    filterSubscriptions(items, { query: 'vps', type: 'recurring' }, { today })
    expect(items).toEqual(snapshot)
    expect(hasSubscriptionFilters()).toBe(false)
    expect(hasSubscriptionFilters({ query: '  ' })).toBe(false)
    expect(hasSubscriptionFilters({ risk: 'ok' })).toBe(true)
  })
})
