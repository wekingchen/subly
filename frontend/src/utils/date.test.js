import { describe, expect, it } from 'vitest'

import { daysLeft, parseLocalDate } from './date'

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
