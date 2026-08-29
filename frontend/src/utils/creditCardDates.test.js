import { describe, expect, it } from 'vitest'

import {
  calendarDayDiff,
  countUpcomingCreditCardDues,
  creditCardCycle,
  formatCreditCardDate,
  nearestCreditCardDue
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
