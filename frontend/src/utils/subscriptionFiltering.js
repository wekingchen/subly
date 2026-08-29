import { parseLocalDate } from './date'
import { renewalStatus } from './renewal'

function normalizeText(value) {
  return String(value || '').trim().toLocaleLowerCase('zh-CN')
}

export function hasSubscriptionFilters(filters = {}) {
  return Boolean(normalizeText(filters.query) || filters.type || filters.risk)
}

export function filterSubscriptions(items, filters = {}, options = {}) {
  const query = normalizeText(filters.query)
  const type = filters.type || ''
  const risk = filters.risk || ''

  return (items || []).filter((item) => {
    if (query) {
      const searchable = [item.name, item.plan, item.remark, item.notes]
        .map(normalizeText)
        .join('\n')
      if (!searchable.includes(query)) return false
    }

    if (type && item.billing_type !== type) return false

    if (risk) {
      if (item.billing_type !== 'recurring' || item.is_active === false || item.is_paused === true) return false
      const today = parseLocalDate(options.today || options.now || new Date())
      const endDate = parseLocalDate(item.end_date)
      if (today && endDate && endDate < new Date(today.getFullYear(), today.getMonth(), today.getDate())) return false
      // daysLeft 只认 options.now；today 必须显式映射，否则风险判定会静默改用真实日期。
      if (renewalStatus(item, { ...options, now: today }) !== risk) return false
    }

    return true
  })
}
