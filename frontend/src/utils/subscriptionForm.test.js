import { describe, expect, it } from 'vitest'

import {
  buildSubscriptionPayload,
  canShowKeepaliveToggle,
  cloneSubscriptionForEdit,
  computeNextRenewalDate,
  createBlankSubscriptionForm,
  normalizeKeepaliveScope
} from './subscriptionForm'

describe('createBlankSubscriptionForm', () => {
  it('creates the same defaults used by the subscription form', () => {
    const form = createBlankSubscriptionForm({ now: '2026-07-02' })

    expect(form).toEqual({
      id: null,
      name: '',
      plan: '',
      icon: '',
      amount: 0,
      currency: 'CNY',
      category_id: null,
      payment_method_id: null,
      bundle_id: null,
      billing_type: 'recurring',
      is_keepalive: false,
      cycle: 'month',
      cycle_count: 1,
      start_date: '2026-07-02',
      next_renewal_date: '',
      end_date: null,
      url: '',
      notes: '',
      remark: '',
      ipv4: '',
      ipv6: '',
      remind_days_before: '7,1',
      auto_renew: true,
      is_active: true,
      show_in_calendar: true,
      family_members: []
    })
  })

  it('does not share family member arrays between new forms', () => {
    const first = createBlankSubscriptionForm({ now: '2026-07-02' })
    const second = createBlankSubscriptionForm({ now: '2026-07-02' })

    first.family_members.push('Alice')

    expect(second.family_members).toEqual([])
  })
})

describe('computeNextRenewalDate', () => {
  it('computes the first renewal date after the start date', () => {
    expect(computeNextRenewalDate({
      billing_type: 'recurring',
      start_date: '2024-01-31',
      cycle: 'month',
      cycle_count: 1
    }, '', { today: '2024-01-31' })).toBe('2024-02-29')
  })

  it('advances historical start dates to the next upcoming renewal', () => {
    expect(computeNextRenewalDate({
      billing_type: 'recurring',
      start_date: '2024-01-31',
      cycle: 'month',
      cycle_count: 1
    }, '', { today: '2024-03-01' })).toBe('2024-03-29')
  })

  it('computes the next date for weekly recurring subscriptions', () => {
    expect(computeNextRenewalDate({
      billing_type: 'recurring',
      start_date: '2024-01-01',
      cycle: 'week',
      cycle_count: 2
    }, '', { today: '2024-01-10' })).toBe('2024-01-15')
  })

  it('advances daily historical subscriptions beyond one thousand cycles', () => {
    expect(computeNextRenewalDate({
      billing_type: 'recurring',
      start_date: '2020-01-01',
      cycle: 'day',
      cycle_count: 1
    }, '', { today: '2024-01-05' })).toBe('2024-01-05')
  })

  it('clears the next date for one-time subscriptions', () => {
    expect(computeNextRenewalDate({
      billing_type: 'one_time',
      start_date: '2024-01-01',
      cycle: 'month',
      cycle_count: 1
    }, '2024-02-01')).toBe('')
  })

  it('keeps the current date when recurring form has no start date', () => {
    expect(computeNextRenewalDate({
      billing_type: 'recurring',
      start_date: '',
      cycle: 'month',
      cycle_count: 1
    }, '2024-02-01')).toBe('2024-02-01')
  })
})

describe('keepalive scope helpers', () => {
  const categories = [
    { id: 1, name: '电信运营商 / Carrier (SIM 保号)' },
    { id: 2, name: 'AI' }
  ]

  it('shows the keepalive toggle only for carrier recurring subscriptions', () => {
    expect(canShowKeepaliveToggle({ billing_type: 'recurring', category_id: 1 }, categories)).toBe(true)
    expect(canShowKeepaliveToggle({ billing_type: 'recurring', category_id: 2 }, categories)).toBe(false)
    expect(canShowKeepaliveToggle({ billing_type: 'one_time', category_id: 1 }, categories)).toBe(false)
  })

  it('clears keepalive when initialized with a non-carrier category', () => {
    const form = { billing_type: 'recurring', category_id: 2, is_keepalive: true }

    normalizeKeepaliveScope(form, categories)

    expect(form.is_keepalive).toBe(false)
  })

  it('clears keepalive and auto-renew when switching to one-time billing', () => {
    const form = { billing_type: 'one_time', category_id: 1, is_keepalive: true, auto_renew: true }

    normalizeKeepaliveScope(form, categories)

    expect(form.is_keepalive).toBe(false)
    expect(form.auto_renew).toBe(false)
  })

  it('keeps keepalive while categories have not loaded for an existing categorized subscription', () => {
    const form = { billing_type: 'recurring', category_id: 1, is_keepalive: true }

    normalizeKeepaliveScope(form, [])

    expect(form.is_keepalive).toBe(true)
  })
})

describe('cloneSubscriptionForEdit', () => {
  it('normalizes empty renewal date and clones family members', () => {
    const subscription = {
      id: 3,
      name: 'Test',
      next_renewal_date: null,
      family_members: ['Alice'],
      sort: 7,
      last_renewed_at: '2024-01-01'
    }
    const form = cloneSubscriptionForEdit(subscription)

    form.family_members.push('Bob')

    expect(form.next_renewal_date).toBe('')
    expect(form.sort).toBe(7)
    expect(form.last_renewed_at).toBe('2024-01-01')
    expect(subscription.family_members).toEqual(['Alice'])
  })
})

describe('buildSubscriptionPayload', () => {
  it('deletes empty next renewal date without mutating the form', () => {
    const form = { id: 1, name: 'Test', next_renewal_date: '', bundle_id: 2 }
    const payload = buildSubscriptionPayload(form)

    expect(payload).toEqual({ id: 1, name: 'Test', bundle_id: 2 })
    expect(form).toEqual({ id: 1, name: 'Test', next_renewal_date: '', bundle_id: 2 })
  })

  it('keeps non-empty next renewal date', () => {
    expect(buildSubscriptionPayload({
      id: 1,
      name: 'Test',
      next_renewal_date: '2024-02-01'
    })).toEqual({
      id: 1,
      name: 'Test',
      next_renewal_date: '2024-02-01'
    })
  })
})
