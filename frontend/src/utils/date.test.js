import { describe, expect, it } from 'vitest'

import { addCycleDate, daysLeft, parseLocalDate, toISODate } from './date'

describe('parseLocalDate', () => {
  it('returns null for empty or invalid values', () => {
    expect(parseLocalDate(null)).toBeNull()
    expect(parseLocalDate('')).toBeNull()
    expect(parseLocalDate('not-a-date')).toBeNull()
  })

  it('clones valid Date instances', () => {
    const original = new Date(2024, 0, 2, 3, 4, 5)
    const parsed = parseLocalDate(original)

    expect(parsed).not.toBe(original)
    expect(parsed.getTime()).toBe(original.getTime())
  })

  it('parses YYYY-MM-DD as a local calendar date', () => {
    const parsed = parseLocalDate('2024-01-02')

    expect(parsed.getFullYear()).toBe(2024)
    expect(parsed.getMonth()).toBe(0)
    expect(parsed.getDate()).toBe(2)
    expect(parsed.getHours()).toBe(0)
  })

  it('parses date-time strings by their date prefix', () => {
    const parsed = parseLocalDate('2024-01-02T23:59:59Z')

    expect(parsed.getFullYear()).toBe(2024)
    expect(parsed.getMonth()).toBe(0)
    expect(parsed.getDate()).toBe(2)
    expect(parsed.getHours()).toBe(0)
  })
})

describe('daysLeft', () => {
  it('uses the explicit now option for deterministic date math', () => {
    expect(daysLeft('2024-01-02', { now: '2024-01-01' })).toBe(1)
    expect(daysLeft('2024-01-01', { now: '2024-01-01' })).toBe(0)
    expect(daysLeft('2023-12-31', { now: '2024-01-01' })).toBe(-1)
  })

  it('reads next_renewal_date from objects by default', () => {
    expect(daysLeft({ next_renewal_date: '2024-01-05' }, { now: '2024-01-01' })).toBe(4)
  })

  it('supports a custom field when reading objects', () => {
    expect(daysLeft({ renew_at: '2024-01-03' }, { field: 'renew_at', now: '2024-01-01' })).toBe(2)
  })

  it('returns null for invalid target dates', () => {
    expect(daysLeft({ next_renewal_date: 'bad-date' }, { now: '2024-01-01' })).toBeNull()
  })

  it('uses Math.ceil for partial-day differences', () => {
    const now = new Date(2024, 0, 1, 12, 0, 0)
    expect(daysLeft(new Date(2024, 0, 2, 0, 0, 0), { now })).toBe(1)
  })
})

describe('toISODate', () => {
  it('formats a date as local YYYY-MM-DD', () => {
    expect(toISODate(new Date(2024, 0, 5))).toBe('2024-01-05')
  })

  it('accepts date-only string input', () => {
    expect(toISODate('2024-03-09')).toBe('2024-03-09')
  })

  it('returns empty string for invalid input', () => {
    expect(toISODate(null)).toBe('')
    expect(toISODate('bad')).toBe('')
  })
})

describe('addCycleDate', () => {
  it('adds day and week cycles', () => {
    expect(toISODate(addCycleDate('2024-01-01', 'day', 3))).toBe('2024-01-04')
    expect(toISODate(addCycleDate('2024-01-01', 'week', 2))).toBe('2024-01-15')
  })

  it('handles month-end and leap year', () => {
    expect(toISODate(addCycleDate('2024-01-31', 'month', 1))).toBe('2024-02-29')
    expect(toISODate(addCycleDate('2023-01-31', 'month', 1))).toBe('2023-02-28')
  })

  it('handles year cycle on leap day', () => {
    expect(toISODate(addCycleDate('2024-02-29', 'year', 1))).toBe('2025-02-28')
  })

  it('normalizes non-positive count to one', () => {
    expect(toISODate(addCycleDate('2024-01-01', 'month', 0))).toBe('2024-02-01')
    expect(toISODate(addCycleDate('2024-01-01', 'month', -2))).toBe('2024-02-01')
  })

  it('defaults unknown cycle to month', () => {
    expect(toISODate(addCycleDate('2024-01-15', 'unknown', 1))).toBe('2024-02-15')
  })
})
