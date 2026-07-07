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

// 到期文案：复用 daysLeft，过期/今天/N 天用统一 i18n key。
// 保号订阅（item.is_keepalive）切到 sub.keepalive.* 文案；options.keepalive 仅供测试覆写。
export function dueText(item, t, options = {}) {
  const d = daysLeft(item, options)
  if (d === null) return ''
  const ka = options.keepalive ?? item?.is_keepalive
  if (d < 0) return ka ? t('sub.keepalive.expiredTag') : t('sub.expiredTag')
  if (d === 0) return ka ? t('sub.keepalive.todayTag') : t('dashboard.today')
  return ka ? t('sub.keepalive.daysLeft', { n: d }) : t('dashboard.daysLeft', { n: d })
}
