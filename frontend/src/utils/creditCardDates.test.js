import { describe, expect, it } from 'vitest'

import {
  buildRepaidScopeText,
  calendarDayDiff,
  countUpcomingCreditCardDues,
  creditCardCycle,
  formatCreditCardDate,
  formatCycleMonth,
  nearestCreditCardDue,
  orderCards,
  sortCardsByDue,
  statementCycleLabel
} from './creditCardDates'

describe('calendarDayDiff', () => {
  it('compares local calendar dates without time-of-day drift', () => {
    expect(calendarDayDiff('2026-03-08T23:59:00Z', '2026-03-09')).toBe(1)
    expect(calendarDayDiff(new Date(2026, 2, 8, 23), new Date(2026, 2, 9, 1))).toBe(1)
  })

  it('returns null for invalid dates', () => {
    expect(calendarDayDiff('bad', '2026-03-09')).toBeNull()
  })
})

describe('creditCardCycle', () => {
  const card = {
    next_statement_date: '2026-08-10',
    next_due_date: '2026-08-28',
    statement_to_due_days: 18
  }

  it('places today proportionally on the real statement-to-due interval', () => {
    const cycle = creditCardCycle(card, '2026-08-19')

    expect(cycle.phase).toBe('repayment-window')
    expect(cycle.spanDays).toBe(18)
    expect(cycle.daysUntilDue).toBe(9)
    expect(cycle.progress).toBe(50)
  })

  it('distinguishes dates before the statement and after the due date', () => {
    expect(creditCardCycle(card, '2026-08-01').phase).toBe('before-statement')
    expect(creditCardCycle(card, '2026-08-29').phase).toBe('overdue')
  })

  it('falls back to dates when the derived span is absent', () => {
    expect(creditCardCycle({ ...card, statement_to_due_days: null }, '2026-08-19').spanDays).toBe(18)
  })

  it('marks incomplete derived dates as unknown instead of inventing a cycle', () => {
    expect(creditCardCycle({ next_statement_date: '2026-08-10' }).valid).toBe(false)
  })
})

describe('credit card due summaries', () => {
  const cards = [
    { id: 1, is_active: true, next_due_date: '2026-08-30' },
    { id: 2, is_active: true, next_due_date: '2026-09-08' },
    { id: 3, is_active: false, next_due_date: '2026-08-29' },
    { id: 4, is_active: true, next_due_date: '2026-08-20' }
  ]

  it('counts only active, non-overdue cards within the requested horizon', () => {
    expect(countUpcomingCreditCardDues(cards, '2026-08-29', 7)).toBe(1)
  })

  it('finds the nearest non-overdue due date', () => {
    expect(nearestCreditCardDue(cards, '2026-08-29')).toEqual({ card: cards[0], days: 1 })
  })

  it('formats date-only values as local Chinese dates', () => {
    expect(formatCreditCardDate('2026-08-30')).toContain('8月')
    expect(formatCreditCardDate('bad')).toBe('—')
  })
})

describe('sortCardsByDue', () => {
  // days_until_due 是后端按业务时区派生的（浏览器不自算「今天」，避免跨时区把当天到期的卡沉底）
  const cards = [
    { id: 1, is_active: true, days_until_due: 19 },
    { id: 2, is_active: true, days_until_due: 4 },
    { id: 3, is_active: false, days_until_due: 1 },  // 停用：沉底
    { id: 4, is_active: true, days_until_due: -1 },  // 已过（派生值不该出现，防御性）
    { id: 5, is_active: true, days_until_due: null } // 日期缺失：沉底
  ]

  it('启用卡按后端派生的距还款天数由近到远，停用/无效沉底且组内保持原顺序', () => {
    expect(sortCardsByDue(cards).map((c) => c.id)).toEqual([2, 1, 4, 5, 3])
  })

  it('同日还款保持输入顺序（稳定排序，不因相等比较打乱）', () => {
    const sameDay = [
      { id: 7, is_active: true, days_until_due: 9 },
      { id: 8, is_active: true, days_until_due: 9 }
    ]
    expect(sortCardsByDue(sameDay).map((c) => c.id)).toEqual([7, 8])
  })

  it('不改动输入数组（纯函数，computed 依赖才可控）', () => {
    const input = [...cards]
    sortCardsByDue(cards)
    expect(cards).toEqual(input)
  })

  it('标记还款顺延后 days_until_due 变远，卡片即排到后面（重排语义）', () => {
    const before = [
      { id: 1, is_active: true, days_until_due: 4 },
      { id: 2, is_active: true, days_until_due: 19 }
    ]
    expect(sortCardsByDue(before).map((c) => c.id)).toEqual([1, 2])
    // 卡 1 标记已还款 → 顺延到下期，越过卡 2
    const after = [
      { id: 1, is_active: true, days_until_due: 32 },
      { id: 2, is_active: true, days_until_due: 19 }
    ]
    expect(sortCardsByDue(after).map((c) => c.id)).toEqual([2, 1])
  })
})

describe('orderCards（页面排序分支）', () => {
  const cards = [
    { id: 1, is_active: true, days_until_due: 19, interest_free_days: 31 },
    { id: 2, is_active: true, days_until_due: 4, interest_free_days: 50 },
    { id: 3, is_active: false, days_until_due: 1, interest_free_days: 99 },
    { id: 4, is_active: true, days_until_due: 10, interest_free_days: null }
  ]

  it('默认按还款日由近到远（页面接线的回归防线：visibleCards 必须走这里）', () => {
    expect(orderCards(cards).map((c) => c.id)).toEqual([2, 4, 1, 3])
  })

  it('byInterestFree 时按免息天数降序，停用/缺失沉底（沿用免息排序口径）', () => {
    expect(orderCards(cards, { byInterestFree: true }).map((c) => c.id)).toEqual([2, 1, 4, 3])
  })
})

describe('statementCycleLabel', () => {
  it('按账单月份命名（用户口径：26年8月账单）', () => {
    expect(statementCycleLabel({ bill_period_end: '2026-08-31', statement_date: '2026-08-31' })).toBe('26年8月')
    // 仅出账日的银行（招行/中信/平安/民生）：statement_date 兜底
    expect(statementCycleLabel({ bill_period_end: null, statement_date: '2027-01-15' })).toBe('27年1月')
    expect(statementCycleLabel({ statement_date: '2026-12-01' })).toBe('26年12月')
  })

  it('无日期回退 null，由调用方决定未知期展示', () => {
    expect(statementCycleLabel({ bill_period_end: null, statement_date: null })).toBeNull()
    expect(statementCycleLabel(null)).toBeNull()
  })

  it('formatCycleMonth 跨世纪取两位年份', () => {
    expect(formatCycleMonth('2099-06-30')).toBe('99年6月')
    expect(formatCycleMonth('bad')).toBeNull()
  })
})

describe('buildRepaidScopeText', () => {
  const t = (key, params = {}) => {
    const table = {
      'creditCards.statementCycleNames': `${params.cycles}账单`,
      'creditCards.unknownCycleCount': `${params.n} 笔未知月份账单`,
      'creditCards.outstandingCountOnly': `${params.n} 笔账单`,
      'creditCards.scopeJoin': '及'
    }
    return table[key]
  }

  it('有月份时按月份列出', () => {
    expect(buildRepaidScopeText({ cycles: ['26年8月', '26年7月'], unknown_cycle_count: 0, count: 2 }, t))
      .toBe('26年8月、26年7月账单')
  })

  it('混合未知月份时补笔数，确认范围=实际标记范围', () => {
    expect(buildRepaidScopeText({ cycles: ['26年8月'], unknown_cycle_count: 1, count: 2 }, t))
      .toBe('26年8月账单及1 笔未知月份账单')
  })

  it('全部未知月份回退笔数', () => {
    expect(buildRepaidScopeText({ cycles: [], unknown_cycle_count: 2, count: 2 }, t))
      .toBe('2 笔未知月份账单')
  })
})
