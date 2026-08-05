import { describe, expect, it } from 'vitest'

import { buildFutureTrend, monthKeyAt, normalizeTrendMonths } from './trend'

describe('trend month helpers', () => {
  it('normalizes supported windows and falls back to six months', () => {
    expect(normalizeTrendMonths(3)).toBe(3)
    expect(normalizeTrendMonths('12')).toBe(12)
    expect(normalizeTrendMonths(8)).toBe(6)
  })

  it('builds month keys across year boundaries', () => {
    expect(monthKeyAt(new Date(2026, 10, 15), 0)).toBe('2026-11')
    expect(monthKeyAt(new Date(2026, 10, 15), 2)).toBe('2027-01')
  })
})

describe('buildFutureTrend', () => {
  const monthly = {
    id: 1,
    name: 'Monthly',
    billing_type: 'recurring',
    is_active: true,
    is_paused: false,
    show_in_calendar: true,
    next_renewal_date: '2026-11-20',
    cycle: 'month',
    cycle_count: 1,
    amount: 10,
    amount_in_base: 10
  }

  it('fills empty months and aggregates future occurrences', () => {
    expect(buildFutureTrend([monthly], 3, { now: new Date(2026, 10, 15) })).toEqual([
      { month: '2026-11', amount: 10 },
      { month: '2026-12', amount: 10 },
      { month: '2027-01', amount: 10 }
    ])
  })

  it('keeps an inclusive end date and excludes later occurrences', () => {
    const ended = { ...monthly, end_date: '2026-12-20' }

    expect(buildFutureTrend([ended], 3, { now: new Date(2026, 10, 15) })).toEqual([
      { month: '2026-11', amount: 10 },
      { month: '2026-12', amount: 10 },
      { month: '2027-01', amount: 0 }
    ])
  })

  it('supports twelve-month windows without dropping zero months', () => {
    const rows = buildFutureTrend([], 12, { now: new Date(2026, 6, 5) })

    expect(rows).toHaveLength(12)
    expect(rows[0]).toEqual({ month: '2026-07', amount: 0 })
    expect(rows[11]).toEqual({ month: '2027-06', amount: 0 })
  })
})
