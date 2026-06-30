const DAY_MS = 86400000
const DATE_ONLY_RE = /^(\d{4})-(\d{2})-(\d{2})(?:$|[T\s])/

export function parseLocalDate(value) {
  if (!value) return null
  if (value instanceof Date) {
    const time = value.getTime()
    return Number.isNaN(time) ? null : new Date(time)
  }
  const m = typeof value === 'string' && value.match(DATE_ONLY_RE)
  if (m) return new Date(Number(m[1]), Number(m[2]) - 1, Number(m[3]))
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? null : date
}

export function daysLeft(valueOrItem, options = {}) {
  const field = options.field || 'next_renewal_date'
  const value = valueOrItem && typeof valueOrItem === 'object' && !(valueOrItem instanceof Date)
    ? valueOrItem[field]
    : valueOrItem
  const target = parseLocalDate(value)
  if (!target) return null
  const now = parseLocalDate(options.now) || new Date()
  return Math.ceil((target - now) / DAY_MS)
}
