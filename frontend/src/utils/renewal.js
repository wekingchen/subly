import { daysLeft } from './date'

function isRecurring(item) {
  return item?.billing_type === 'recurring'
}

function hasRenewalDate(item, field = 'next_renewal_date') {
  return Boolean(item?.[field])
}

export function renewalStatus(item, options = {}) {
  const field = options.field || 'next_renewal_date'
  const emptyStatus = options.emptyStatus || 'oneTime'
  const soonDays = options.soonDays ?? 7
  if (!item) return emptyStatus
  if (item.billing_type && !isRecurring(item)) return options.oneTimeStatus || 'oneTime'
  if (!hasRenewalDate(item, field)) return emptyStatus
  const d = daysLeft(item, { ...options, field })
  if (d === null) return emptyStatus
  if (d < 0) return 'overdue'
  if (d <= soonDays) return 'soon'
  return 'ok'
}

export function dueClass(item, options = {}) {
  const status = renewalStatus(item, options)
  if (status === 'overdue' || status === 'soon') return status
  return ''
}

export function isExpired(item, options = {}) {
  if (!isRecurring(item) || !hasRenewalDate(item, options.field || 'next_renewal_date')) return false
  const d = daysLeft(item, options)
  return d !== null && d < 0
}

export function isSoon(item, options = {}) {
  if (!isRecurring(item) || !hasRenewalDate(item, options.field || 'next_renewal_date')) return false
  const d = daysLeft(item, options)
  const soonDays = options.soonDays ?? 7
  return d !== null && d >= 0 && d <= soonDays
}

export function radarBucket(item, options = {}) {
  const field = options.field || 'next_renewal_date'
  if (!item || (item.billing_type && !isRecurring(item)) || !hasRenewalDate(item, field)) return null
  if (!options.includeHidden && item.show_in_calendar === false) return null
  const d = daysLeft(item, { ...options, field })
  const horizon = options.horizon ?? 30
  const firstWindow = options.firstWindow ?? 3
  const secondWindow = options.secondWindow ?? 7
  if (d === null || d > horizon) return null
  if (d < 0) return 'overdue'
  if (d <= firstWindow) return 'd3'
  if (d <= secondWindow) return 'd7'
  return 'd30'
}

export function groupRenewalStatus(items, options = {}) {
  if (!items?.length) return options.emptyStatus || ''
  const statuses = items.map((item) => renewalStatus(item, { emptyStatus: 'ok', ...options }))
  if (statuses.includes('overdue')) return 'overdue'
  if (statuses.includes('soon')) return 'soon'
  return 'ok'
}
