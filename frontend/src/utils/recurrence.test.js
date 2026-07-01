import { describe, expect, it } from 'vitest'

import { expandRenewalsInRange, groupRenewalEventsByDate } from './recurrence'

const baseSub = (overrides = {}) => ({
  id: 1,
  name: 'Monthly VPS',
  billing_type: 'recurring',
  is_active: true,
  show_in_calendar: true,
  cycle: 'month',
  cycle_count: 1,
  next_renewal_date: '2026-07-05',
  amount: 10,
  currency: 'CNY',
  ...overrides
})

describe('expandRenewalsInRange', () => {
  it('projects monthly subscriptions into future months when there is no end date', () => {
    const events = expandRenewalsInRange([baseSub()], '2026-08-01', '2026-08-31')

    expect(events).toHaveLength(1)
    expect(events[0].occurrence_date).toBe('2026-08-05')
    expect(events[0].next_renewal_date).toBe('2026-08-05')
    expect(events[0].id).toBe('1:2026-08-05')
    expect(events[0].occurrence_origin_id).toBe(1)
  })

  it('can generate multiple daily occurrences in the same range', () => {
    const events = expandRenewalsInRange([
      baseSub({ cycle: 'day', cycle_count: 2, next_renewal_date: '2026-07-01' })
    ], '2026-07-01', '2026-07-07')

    expect(events.map((e) => e.occurrence_date)).toEqual([
      '2026-07-01',
      '2026-07-03',
      '2026-07-05',
      '2026-07-07'
    ])
  })

  it('can generate multiple weekly occurrences in the same range', () => {
    const events = expandRenewalsInRange([
      baseSub({ cycle: 'week', cycle_count: 1, next_renewal_date: '2026-07-01' })
    ], '2026-07-01', '2026-07-31')

    expect(events.map((e) => e.occurrence_date)).toEqual([
      '2026-07-01',
      '2026-07-08',
      '2026-07-15',
      '2026-07-22',
      '2026-07-29'
    ])
  })

  it('treats end_date as an inclusive cutoff', () => {
    const included = expandRenewalsInRange([
      baseSub({ end_date: '2026-08-05' })
    ], '2026-08-01', '2026-08-31')
    const excluded = expandRenewalsInRange([
      baseSub({ end_date: '2026-08-04' })
    ], '2026-08-01', '2026-08-31')

    expect(included.map((e) => e.occurrence_date)).toEqual(['2026-08-05'])
    expect(excluded).toHaveLength(0)
  })

  it('filters hidden, inactive, one-time and date-less subscriptions', () => {
    const events = expandRenewalsInRange([
      baseSub({ id: 1, show_in_calendar: false }),
      baseSub({ id: 2, is_active: false }),
      baseSub({ id: 3, billing_type: 'one_time' }),
      baseSub({ id: 4, next_renewal_date: '' }),
      null
    ], '2026-07-01', '2026-07-31')

    expect(events).toHaveLength(0)
  })

  it('groups events by occurrence date', () => {
    const events = expandRenewalsInRange([
      baseSub({ id: 1, next_renewal_date: '2026-07-05' }),
      baseSub({ id: 2, next_renewal_date: '2026-07-05' })
    ], '2026-07-01', '2026-07-31')
    const grouped = groupRenewalEventsByDate(events)

    expect(grouped.get('2026-07-05')).toHaveLength(2)
  })
})
