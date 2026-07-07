import { describe, expect, it } from 'vitest'

import {
  dueText,
  groupRenewalStatus,
  isExpired,
  isSoon,
  radarBucket,
  renewalStatus
} from './renewal'

const NOW = '2024-01-01'
const recurring = (next, extra = {}) => ({
  billing_type: 'recurring',
  next_renewal_date: next,
  ...extra
})

describe('renewalStatus', () => {
  it('returns oneTime for empty, non-recurring or date-less items by default', () => {
    expect(renewalStatus(null, { now: NOW })).toBe('oneTime')
    expect(renewalStatus({ billing_type: 'one_time' }, { now: NOW })).toBe('oneTime')
    expect(renewalStatus({ billing_type: 'recurring' }, { now: NOW })).toBe('oneTime')
  })

  it('supports custom empty and one-time statuses', () => {
    expect(renewalStatus(null, { now: NOW, emptyStatus: 'empty' })).toBe('empty')
    expect(renewalStatus({ billing_type: 'one_time' }, { now: NOW, oneTimeStatus: 'lifetime' })).toBe('lifetime')
  })

  it('classifies overdue, soon and ok subscriptions', () => {
    expect(renewalStatus(recurring('2023-12-31'), { now: NOW })).toBe('overdue')
    expect(renewalStatus(recurring('2024-01-01'), { now: NOW })).toBe('soon')
    expect(renewalStatus(recurring('2024-01-08'), { now: NOW })).toBe('soon')
    expect(renewalStatus(recurring('2024-01-09'), { now: NOW })).toBe('ok')
  })

  it('supports custom field and soonDays options', () => {
    const item = { billing_type: 'recurring', renew_at: '2024-01-05' }
    expect(renewalStatus(item, { field: 'renew_at', soonDays: 3, now: NOW })).toBe('ok')
    expect(renewalStatus(item, { field: 'renew_at', soonDays: 4, now: NOW })).toBe('soon')
  })
})

describe('isExpired', () => {
  it('returns true only for recurring subscriptions before today', () => {
    expect(isExpired(recurring('2023-12-31'), { now: NOW })).toBe(true)
    expect(isExpired(recurring('2024-01-01'), { now: NOW })).toBe(false)
    expect(isExpired({ billing_type: 'one_time', next_renewal_date: '2023-12-31' }, { now: NOW })).toBe(false)
    expect(isExpired({ billing_type: 'recurring' }, { now: NOW })).toBe(false)
  })
})

describe('isSoon', () => {
  it('returns true for recurring subscriptions inside the soon window', () => {
    expect(isSoon(recurring('2024-01-01'), { now: NOW })).toBe(true)
    expect(isSoon(recurring('2024-01-08'), { now: NOW })).toBe(true)
    expect(isSoon(recurring('2023-12-31'), { now: NOW })).toBe(false)
    expect(isSoon(recurring('2024-01-09'), { now: NOW })).toBe(false)
  })

  it('supports custom soonDays', () => {
    expect(isSoon(recurring('2024-01-04'), { now: NOW, soonDays: 2 })).toBe(false)
    expect(isSoon(recurring('2024-01-04'), { now: NOW, soonDays: 3 })).toBe(true)
  })

  it('supports a zero-day soon window for today only', () => {
    expect(isSoon(recurring('2024-01-01'), { now: NOW, soonDays: 0 })).toBe(true)
    expect(isSoon(recurring('2024-01-02'), { now: NOW, soonDays: 0 })).toBe(false)
  })
})

describe('radarBucket', () => {
  it('ignores hidden calendar items by default', () => {
    expect(radarBucket(recurring('2024-01-02', { show_in_calendar: false }), { now: NOW })).toBeNull()
  })

  it('can include hidden calendar items explicitly', () => {
    expect(radarBucket(recurring('2024-01-02', { show_in_calendar: false }), { now: NOW, includeHidden: true })).toBe('d3')
  })

  it('classifies overdue and upcoming windows', () => {
    expect(radarBucket(recurring('2023-12-31'), { now: NOW })).toBe('overdue')
    expect(radarBucket(recurring('2024-01-04'), { now: NOW })).toBe('d3')
    expect(radarBucket(recurring('2024-01-08'), { now: NOW })).toBe('d7')
    expect(radarBucket(recurring('2024-01-20'), { now: NOW })).toBe('d30')
    expect(radarBucket(recurring('2024-01-31'), { now: NOW })).toBe('d30')
  })

  it('returns null outside the horizon or for unsupported items', () => {
    expect(radarBucket(recurring('2024-02-15'), { now: NOW })).toBeNull()
    expect(radarBucket({ billing_type: 'one_time', next_renewal_date: '2024-01-02' }, { now: NOW })).toBeNull()
    expect(radarBucket({ billing_type: 'recurring' }, { now: NOW })).toBeNull()
  })

  it('supports custom window boundaries', () => {
    expect(radarBucket(recurring('2024-01-06'), { now: NOW, firstWindow: 5 })).toBe('d3')
    expect(radarBucket(recurring('2024-01-10'), { now: NOW, secondWindow: 9 })).toBe('d7')
  })
})

describe('groupRenewalStatus', () => {
  it('returns the configured empty status for empty groups', () => {
    expect(groupRenewalStatus([], { now: NOW })).toBe('')
    expect(groupRenewalStatus([], { now: NOW, emptyStatus: 'empty' })).toBe('empty')
  })

  it('prioritizes overdue over soon and ok', () => {
    expect(groupRenewalStatus([recurring('2024-01-09'), recurring('2023-12-31')], { now: NOW })).toBe('overdue')
  })

  it('returns soon when no item is overdue but at least one is soon', () => {
    expect(groupRenewalStatus([recurring('2024-01-09'), recurring('2024-01-08')], { now: NOW })).toBe('soon')
  })

  it('returns ok when all items are safe', () => {
    expect(groupRenewalStatus([recurring('2024-01-09'), recurring('2024-01-10')], { now: NOW })).toBe('ok')
  })
})

describe('dueText', () => {
  // mock t：返回 key + 参数，便于断言走了哪条分支
  const t = (key, params) => key === 'dashboard.daysLeft' ? `d:${params.n}` : key

  it('returns empty string when daysLeft is null (non-recurring or dateless)', () => {
    expect(dueText({ billing_type: 'one_time' }, t, { now: NOW })).toBe('')
    expect(dueText({ billing_type: 'recurring' }, t, { now: NOW })).toBe('')
    expect(dueText(null, t, { now: NOW })).toBe('')
  })

  it('returns the expired tag when overdue', () => {
    expect(dueText(recurring('2023-12-31'), t, { now: NOW })).toBe('sub.expiredTag')
  })

  it('returns today text when due today', () => {
    expect(dueText(recurring('2024-01-01'), t, { now: NOW })).toBe('dashboard.today')
  })

  it('returns daysLeft text with n when in the future', () => {
    expect(dueText(recurring('2024-01-05'), t, { now: NOW })).toBe('d:4')
  })
})

describe('dueText (keepalive)', () => {
  // mock t：带参的 daysLeft 两个 key 都处理，其余返回 key 本身用于断言分支
  const t = (key, params) => {
    if (key === 'dashboard.daysLeft') return `d:${params.n}`
    if (key === 'sub.keepalive.daysLeft') return `ka:${params.n}`
    return key
  }

  it('uses keepalive tags when item.is_keepalive is true', () => {
    const ka = (next) => recurring(next, { is_keepalive: true })
    expect(dueText(ka('2023-12-31'), t, { now: NOW })).toBe('sub.keepalive.expiredTag')
    expect(dueText(ka('2024-01-01'), t, { now: NOW })).toBe('sub.keepalive.todayTag')
    expect(dueText(ka('2024-01-05'), t, { now: NOW })).toBe('ka:4')
  })

  it('options.keepalive overrides item flag (for testing)', () => {
    expect(dueText(recurring('2023-12-31'), t, { now: NOW, keepalive: true })).toBe('sub.keepalive.expiredTag')
  })

  it('falls back to renew tags when is_keepalive is false/absent', () => {
    expect(dueText(recurring('2023-12-31'), t, { now: NOW })).toBe('sub.expiredTag')
    expect(dueText(recurring('2024-01-01'), t, { now: NOW })).toBe('dashboard.today')
  })
})
